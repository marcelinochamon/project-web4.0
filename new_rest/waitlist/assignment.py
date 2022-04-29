from datetime import datetime
from django.utils import timezone

tz = timezone.get_default_timezone()

# RETURNS BEST PERSON IN LIST OF WAITING PEOPLE FOR A GIVEN TABLE
# ATTRIBUTES TO ACCESS: table.seats, table.server, 
# for person in waiting_people
# person.party_size, person.wait_time, person.arrival_time
def find_best_person(table, waiting_people):
    """
    Function finds the best party in list of waiting people to assign to a given empty table 
    inputs: Table object, list of Wait objects
    return: Wait object
    """
    # Get new party from top of waitlist
    new_party = waiting_people.pop()
    return new_party


def assign_tables():
    from .models import Table, Wait
    # Get empty tables
    empty_tables = list(Table.objects.filter(party = "Empty"))
    # Get list of people on waitlist, ordered by longest to shortest wait time
    waiting_people = list(Wait.objects.all().order_by("arrival_time"))
    # Loop through empty tables
    for table in empty_tables:
        # Check if anyone is waiting on the waitlist
        if len(waiting_people) == 0:
            print("Nobody on waitlist")
            break
        else:
            new_party = find_best_person(table, waiting_people)
            # Assign table party the new name
            table.party = new_party.name
            # Initialize seated time
            table.time_seated = datetime.now(tz)
            # Save new Table object
            table.save()
            # Delete off the waitlist
            new_party.delete()
            print("Assigned Party {} to table {}".format(table.party, table.number))