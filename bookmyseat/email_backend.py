
from django.core.mail.backends.smtp import EmailBackend as DjangoEmailBackend


class EmailBackend(DjangoEmailBackend):
    def open(self):
        if self.connection:
            return False

        import smtplib

        try:
            self.connection = smtplib.SMTP(
                self.host,
                self.port,
                timeout=self.timeout,
            )

            if self.use_tls:
                self.connection.ehlo()
                self.connection.starttls()
                self.connection.ehlo()

            if self.username and self.password:
                self.connection.login(self.username, self.password)

            return True

        except Exception:
            self.close()
            if not self.fail_silently:
                raise
            return None
