import io
import os
import tarfile
from datetime import datetime
from typing import Dict, Optional
import requests
import logging
from geoip import GeoIP2, GeoIP2Exception
from geoip2.errors import AddressNotFoundError
from utils import get_client_ip
import tempfile

logger = logging.getLogger(__name__)


class MaxMindService:
    cache_date_key: str = "GEOIP_REQUIRE_UPDATE"

    def __init__(self, redis_client, license_key: str = None):
        self.redis_client = redis_client
        self.dataset_path = tempfile.gettempdir() + "/GeoLite2-Country.mmdb"
        self._client = None
        self.MAXMIND_LICENSE_KEY: str = license_key
        self.MAXMIND_COUNTRY_DATABASE: str = (
                "https://download.maxmind.com/app/geoip_download?edition_id=GeoLite2-Country&suffix=tar.gz&license_key="
                + str(license_key)
        )

    def get_client(self) -> GeoIP2:
        """
        Returns a GeoIP2 client instance.
        """
        if self._client is None:
            self._client = GeoIP2(geoip_path=self.dataset_path)
        return self._client

    def get_country_by_ip(self, ip_address: str) -> Optional[Dict[str, str]]:
        """
        Returns the country location of the IP address.
        """
        try:
            client: GeoIP2 = self.get_client()
            return client.country(ip_address)
        except AddressNotFoundError:
            return None
        except GeoIP2Exception:
            logger.warning(GeoIP2Exception("Could not load a database from %s." % self.dataset_path))
            return None
        except Exception as e:
            logger.exception(e)
            return None

    def get_country_by_request(self, request) -> Optional[Dict[str, str]]:
        """
        Returns the country location of the client making the request.
        """
        ip_address: str = get_client_ip(request)
        return self.get_country_by_ip(ip_address)

    async def _requires_update(self) -> bool:
        if await self.redis_client.get(self.cache_date_key):
            return False
        now = datetime.now()
        end_of_day = datetime(now.year, now.month, now.day, 23, 59, 59)
        remaining_time = end_of_day - now
        cache_timeout = int(remaining_time.total_seconds()) + 1
        await self.redis_client.setex(self.cache_date_key, cache_timeout, 'True')
        return True

    async def download_country_dataset(self) -> None:
        """
        Downloads the GeoIP Country database from MaxMind.
        """
        if not self.MAXMIND_LICENSE_KEY:
            logger.warning(
                "No envvar MAXMIND_LICENSE_KEY. "
                "Cannot download the dataset without this. "
                "Create a MaxMind account."
            )
            return None
        aa = await self._requires_update()
        if os.path.exists(self.dataset_path) and not aa:
            return None

        url = self.MAXMIND_COUNTRY_DATABASE
        response: requests.Response = requests.get(url)
        if not response.ok:
            logger.error(
                "Failed to update GeoIP Country database: " + url + ". Status_code=" + str(response.status_code)
            )
            return None

        with tarfile.open(mode="r:gz", fileobj=io.BytesIO(response.content)) as tar:
            for member in tar.getmembers():
                if member.name.endswith(".mmdb"):
                    buf = tar.extractfile(member)
                    with open(self.dataset_path, "wb") as fd:
                        fd.write(buf.read())
                    break
            else:
                logger.error("No .mmdb file found in the response content.")
