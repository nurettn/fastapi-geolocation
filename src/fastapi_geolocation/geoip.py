import ipaddress
from pydantic import ValidationError
import geoip2.database
from pathlib import Path
import socket

from resources import City, Country


def clean_ipv6_address(ip_str, unpack_ipv4=False,
                       error_message="This is not a valid IPv6 address."):
    """
    Clean an IPv6 address string.

    Raise ValidationError if the address is invalid.

    Replace the longest continuous zero-sequence with "::", remove leading
    zeroes, and make sure all hextets are lowercase.

    Args:
        ip_str: A valid IPv6 address.
        unpack_ipv4: if an IPv4-mapped address is found,
        return the plain IPv4 address (default=False).
        error_message: An error message used in the ValidationError.

    Return a compressed IPv6 address or the same value.
    """
    try:
        addr = ipaddress.IPv6Address(int(ipaddress.IPv6Address(ip_str)))
    except ValueError:
        raise ValidationError(error_message, code='invalid')

    if unpack_ipv4 and addr.ipv4_mapped:
        return str(addr.ipv4_mapped)
    elif addr.ipv4_mapped:
        return '::ffff:%s' % str(addr.ipv4_mapped)

    return str(addr)


def is_valid_ipv6_address(ip_str):
    """
    Return whether or not the `ip_str` string is a valid IPv6 address.
    """
    try:
        ipaddress.IPv6Address(ip_str)
    except ValueError:
        return False
    return True


def validate_ipv4_address(value):
    try:
        ipaddress.IPv4Address(value)
    except ValueError:
        raise ValidationError('Enter a valid IPv4 address.')
    else:
        # Leading zeros are forbidden to avoid ambiguity with the octal
        # notation. This restriction is included in Python 3.9.5+.
        # TODO: Remove when dropping support for PY39.
        if any(
                octet != '0' and octet[0] == '0'
                for octet in value.split('.')
        ):
            raise ValidationError('Enter a valid IPv4 address.')


def validate_ipv6_address(value):
    if not is_valid_ipv6_address(value):
        raise ValidationError('Enter a valid IPv6 address.')


def validate_ipv46_address(value):
    try:
        validate_ipv4_address(value)
    except ValidationError:
        try:
            validate_ipv6_address(value)
        except ValidationError:
            raise ValidationError('Enter a valid IPv4 or IPv6 address.')


ip_address_validator_map = {
    'both': ([validate_ipv46_address], 'Enter a valid IPv4 or IPv6 address.'),
    'ipv4': ([validate_ipv4_address], 'Enter a valid IPv4 address.'),
    'ipv6': ([validate_ipv6_address], 'Enter a valid IPv6 address.'),
}


def ip_address_validators(protocol, unpack_ipv4):
    """
    Depending on the given parameters, return the appropriate validators for
    the GenericIPAddressField.
    """
    if protocol != 'both' and unpack_ipv4:
        raise ValueError(
            "You can only use `unpack_ipv4` if `protocol` is set to 'both'")
    try:
        return ip_address_validator_map[protocol.lower()]
    except KeyError:
        raise ValueError("The protocol '%s' is unknown. Supported: %s"
                         % (protocol, list(ip_address_validator_map)))


class GeoIP2Exception(Exception):
    pass


class GeoIP2:
    # The flags for GeoIP memory caching.
    # Try MODE_MMAP_EXT, MODE_MMAP, MODE_FILE in that order.
    MODE_AUTO = 0
    # Use the C extension with memory map.
    MODE_MMAP_EXT = 1
    # Read from memory map. Pure Python.
    MODE_MMAP = 2
    # Read database as standard file. Pure Python.
    MODE_FILE = 4
    # Load database into memory. Pure Python.
    MODE_MEMORY = 8
    cache_options = frozenset((MODE_AUTO, MODE_MMAP_EXT, MODE_MMAP, MODE_FILE, MODE_MEMORY))

    GEOIP_SETTINGS = {}

    # Paths to the city & country binary databases.
    _city_file = ''
    _country_file = ''

    # Initially, pointers to GeoIP file references are NULL.
    _city = None
    _country = None

    def __init__(self, path=None, cache=0, country=None, city=None, geoip_path=None, geoip_city=None, geoip_country=None):
        """
        Initialize the GeoIP object. No parameters are required to use default
        settings. Keyword arguments may be passed in to customize the locations
        of the GeoIP datasets.

        * path: Base directory to where GeoIP data is located or the full path
            to where the city or country data files (*.mmdb) are located.
            Assumes that both the city and country data sets are located in
            this directory; overrides the GEOIP_PATH setting.

        * cache: The cache settings when opening up the GeoIP datasets. May be
            an integer in (0, 1, 2, 4, 8) corresponding to the MODE_AUTO,
            MODE_MMAP_EXT, MODE_MMAP, MODE_FILE, and MODE_MEMORY,
            `GeoIPOptions` C API settings,  respectively. Defaults to 0,
            meaning MODE_AUTO.

        * country: The name of the GeoIP country data file. Defaults to
            'GeoLite2-Country.mmdb'; overrides the GEOIP_COUNTRY setting.

        * city: The name of the GeoIP city data file. Defaults to
            'GeoLite2-City.mmdb'; overrides the GEOIP_CITY setting.
        """
        # Checking the given cache option.
        if cache in self.cache_options:
            self._cache = cache
        else:
            raise GeoIP2Exception('Invalid GeoIP caching option: %s' % cache)

        self.GEOIP_SETTINGS = {
            'GEOIP_PATH': geoip_path or None,
            'GEOIP_CITY': geoip_city or "GeoLite2-City.mmdb",
            'GEOIP_COUNTRY': geoip_country or "GeoLite2-Country.mmdb",
        }

        # Getting the GeoIP data path.
        path = path or self.GEOIP_SETTINGS['GEOIP_PATH']
        if not path:
            raise GeoIP2Exception('GeoIP path must be provided via parameter or the GEOIP_PATH setting.')
        if not isinstance(path, str):
            raise TypeError('Invalid path type: %s' % type(path).__name__)

        path = Path(path)
        if path.is_dir():
            # Constructing the GeoIP database filenames using the settings
            # dictionary. If the database files for the GeoLite country
            # and/or city datasets exist, then try to open them.
            country_db = path / (country or self.GEOIP_SETTINGS['GEOIP_COUNTRY'])
            if country_db.is_file():
                self._country = geoip2.database.Reader(str(country_db), mode=cache)
                self._country_file = country_db

            city_db = path / (city or self.GEOIP_SETTINGS['GEOIP_CITY'])
            if city_db.is_file():
                self._city = geoip2.database.Reader(str(city_db), mode=cache)
                self._city_file = city_db
            if not self._reader:
                raise GeoIP2Exception('Could not load a database from %s.' % path)
        elif path.is_file():
            # Otherwise, some detective work will be needed to figure out
            # whether the given database path is for the GeoIP country or city
            # databases.
            reader = geoip2.database.Reader(str(path), mode=cache)
            db_type = reader.metadata().database_type

            if db_type.endswith('City'):
                # GeoLite City database detected.
                self._city = reader
                self._city_file = path
            elif db_type.endswith('Country'):
                # GeoIP Country database detected.
                self._country = reader
                self._country_file = path
            else:
                raise GeoIP2Exception('Unable to recognize database edition: %s' % db_type)
        else:
            raise GeoIP2Exception('GeoIP path must be a valid file or directory.')

    @property
    def _reader(self):
        return self._country or self._city

    @property
    def _country_or_city(self):
        if self._country:
            return self._country.country
        else:
            return self._city.city

    def __del__(self):
        # Cleanup any GeoIP file handles lying around.
        if self._reader:
            self._reader.close()

    def __repr__(self):
        meta = self._reader.metadata()
        version = '[v%s.%s]' % (meta.binary_format_major_version, meta.binary_format_minor_version)
        return '<%(cls)s %(version)s _country_file="%(country)s", _city_file="%(city)s">' % {
            'cls': self.__class__.__name__,
            'version': version,
            'country': self._country_file,
            'city': self._city_file,
        }

    def _check_query(self, query, country=False, city=False, city_or_country=False):
        "Check the query and database availability."
        # Making sure a string was passed in for the query.
        if not isinstance(query, str):
            raise TypeError('GeoIP query must be a string, not type %s' % type(query).__name__)

        # Extra checks for the existence of country and city databases.
        if city_or_country and not (self._country or self._city):
            raise GeoIP2Exception('Invalid GeoIP country and city data files.')
        elif country and not self._country:
            raise GeoIP2Exception('Invalid GeoIP country data file: %s' % self._country_file)
        elif city and not self._city:
            raise GeoIP2Exception('Invalid GeoIP city data file: %s' % self._city_file)

        # Return the query string back to the caller. GeoIP2 only takes IP addresses.
        try:
            validate_ipv46_address(query)
        except ValidationError:
            query = socket.gethostbyname(query)

        return query

    def city(self, query):
        """
        Return a dictionary of city information for the given IP address or
        Fully Qualified Domain Name (FQDN). Some information in the dictionary
        may be undefined (None).
        """
        enc_query = self._check_query(query, city=True)
        return City(self._city.city(enc_query))

    def country_code(self, query):
        "Return the country code for the given IP Address or FQDN."
        enc_query = self._check_query(query, city_or_country=True)
        return self.country(enc_query)['country_code']

    def country_name(self, query):
        "Return the country name for the given IP Address or FQDN."
        enc_query = self._check_query(query, city_or_country=True)
        return self.country(enc_query)['country_name']

    def country(self, query):
        """
        Return a dictionary with the country code and name when given an
        IP address or a Fully Qualified Domain Name (FQDN). For example, both
        '24.124.1.80' and 'djangoproject.com' are valid parameters.
        """
        # Returning the country code and name
        enc_query = self._check_query(query, city_or_country=True)
        return Country(self._country_or_city(enc_query))

    # #### Coordinate retrieval routines ####
    def coords(self, query, ordering=('longitude', 'latitude')):
        cdict = self.city(query)
        if cdict is None:
            return None
        else:
            return tuple(cdict[o] for o in ordering)

    def lon_lat(self, query):
        "Return a tuple of the (longitude, latitude) for the given query."
        return self.coords(query)

    def lat_lon(self, query):
        "Return a tuple of the (latitude, longitude) for the given query."
        return self.coords(query, ('latitude', 'longitude'))

    def geos(self, query):
        "Return a GEOS Point object for the given query."
        ll = self.lon_lat(query)
        if ll:
            from django.contrib.gis.geos import Point
            return Point(ll, srid=4326)
        else:
            return None

    # #### GeoIP Database Information Routines ####
    @property
    def info(self):
        "Return information about the GeoIP library and databases in use."
        meta = self._reader.metadata()
        return 'GeoIP Library:\n\t%s.%s\n' % (meta.binary_format_major_version, meta.binary_format_minor_version)

    @classmethod
    def open(cls, full_path, cache):
        return GeoIP2(full_path, cache)
