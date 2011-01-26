from django.db import models
from django.contrib.auth.models import User

class Surveyor(User):

    class Meta:
        app_label = 'odk_dropbox'

    def name(self):
        return self.first_name.title()
