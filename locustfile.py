
from locust import HttpUser, task, between


class BookMyShowUser(HttpUser):
    wait_time = between(1, 3)

    @task
    def browse_movies(self):
        self.client.get("/movies/", name="Browse Movies")