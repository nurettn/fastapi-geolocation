from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from service import MaxMindService


class GeoIPMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, redis_client, license_key: str):
        super().__init__(app)
        self.geolocation_service = MaxMindService(redis_client, license_key=license_key)

    async def dispatch(self, request: Request, call_next):
        await self.geolocation_service.download_country_dataset()

        client_ip = request.client.host
        try:
            response = self.geolocation_service.get_country_by_ip(client_ip)
        except Exception as e:
            response = None

        request.state.geolocation = response
        response = await call_next(request)
        return response
