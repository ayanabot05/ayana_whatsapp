class AsyncIOScheduler:
    def __init__(self, *args, **kwargs):
        self.running = False

    def add_job(self, *args, **kwargs):
        return None

    def get_jobs(self):
        return []

    def start(self):
        self.running = True

    def shutdown(self, wait=False):
        self.running = False
