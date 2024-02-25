# FastAPI Geolocation

`fastapi-geolocation` is a simple middleware package for FastAPI that provides geolocation features by integrating IP-based location lookup. This package is particularly useful for FastAPI applications that need to determine the geographical location of their users.

## Features

- Easy integration with FastAPI applications.
- Utilizes the GeoIP class from Django for location lookup.
- Provides an easy-to-use middleware that enriches requests with geolocation data.

## Installation

To install `fastapi-geolocation`, run the following command:

```bash
pip install fastapi-geolocation
```

## Quick Start
Here is a simple example of how to use fastapi-geolocation in a FastAPI application:
```python3
import aioredis
from fastapi import FastAPI, Request
from fastapi_geolocation import GeoIPMiddleware

app = FastAPI()
redis_client = aioredis.from_url("redis://localhost", encoding="utf-8", decode_responses=True)
app.add_middleware(GeoIPMiddleware, redis_client=redis_client, license_key="mykey")

@app.get('/')
async def index(request: Request):
    geo_data = request.state.geo
    return {
        'country': geo_data.country.name if geo_data else 'Unknown',
    }
```

## Configuration
To set up the middleware, you need to add it to your FastAPI application with the necessary parameters:

redis_client: An instance of aioredis client for caching purpose.
license_key: Your MaxMind license key for the GeoIP database.


## Usage
After adding the middleware to your FastAPI application, you can access the geolocation data in your route handlers using the request.state.geo property.

## Contributing
Contributions are welcome! If you would like to contribute to the project, please follow these steps:

Fork the repository.
Create a new branch for your feature or fix.
Write your code and add tests if applicable.
Submit a pull request with a clear description of your changes.

##  License
fastapi-geolocation is open source software licensed as MIT.

## Credits
This project was inspired by the GeoIP functionality in Django and has been adapted for use in FastAPI applications.

