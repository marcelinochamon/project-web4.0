from django.db import models

# Create your models here.
class Table(models.Model):
    # Table number
    number = models.IntegerField()
    # Guest name
    guest = models.CharField(max_length = 20, default = "Empty")
    # Seating capacity of table
    seats = models.IntegerField()
    # Time seated
    time_seated = models.TimeField()

    def __str__(self):
        name = "Table" + str(self.number)
        return name