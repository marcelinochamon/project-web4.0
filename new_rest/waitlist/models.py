from django.db import models

# Create your models here.
# class Friend(models.Model):
#     name = models.CharField(max_length = 120) # max_length required
#     email = models.EmailField()
#     message = models.TextField(blank=True, null=True) # optional blank = False means required, null = True means nothing is fine
#     school = models.CharField(max_length = 20, default='UT')
#     best_school = models.CharField(max_length = 20, default='UT')

#     def __str__(self):
#         return self.name