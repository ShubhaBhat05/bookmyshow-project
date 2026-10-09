from django.contrib.sessions.middleware import SessionMiddleware


class AdminSessionMiddleware(SessionMiddleware):
    def process_request(self, request):
        if request.path.startswith("/admin/"):
            self.cookie_name = "admin_sessionid"
        else:
            self.cookie_name = "sessionid"

        return super().process_request(request)