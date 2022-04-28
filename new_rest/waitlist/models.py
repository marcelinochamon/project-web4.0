from django.db import models

# Create your models here.

class Wait(models.Model):
     name = models.CharField(max_length = 120) # max_length required
     party_size = models.CharField(max_length = 20)
     dining_time = models.CharField(max_length = 20)
     seated = models.BooleanField(default=False)
     left = models.BooleanField(default=False)


     def __str__(self):
         return self.name
