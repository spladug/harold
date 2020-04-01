class Plugin(object):
    def __init__(self):
        self.services = []

    def add_service(self, service):
        self.services.append(service)
