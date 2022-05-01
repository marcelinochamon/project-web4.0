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
    for people in waiting_people:
        if 0 <= table.seat-people.party <= 1:
            waiting_people.assign_sugg = table.number
            break
        else:
            continue
    waiting_people.objects.all().order_by('assign_sugg','arrival_time')
        
    # Get new party from top of waitlist
    np = waiting_people.pop()
    if np.assign_sugg != 0
        new_party = waiting_people.pop()
    else:
        
    return new_party


def assign_tables():
    from .models import Table, Wait
    # Get empty tables
    empty_tables = list(Table.objects.filter(party = "Empty"))
    # Get list of people on waitlist, ordered by longest to shortest wait time
    waiting_people = list(Wait.objects.filter(assign_sugg = 0).order_by("arrival_time"))
    # Loop through empty tables
    for table in empty_tables:
        # Check if anyone is waiting on the waitlist
        if len(waiting_people) == 0:
            print("Nobody on waitlist")
            break
        else:
            # Get best party for the table
            new_party = find_best_person(table, waiting_people)
            # Change assignment suggestion
            new_party.assign_sugg = table.number
            new_party.save()
            # Change table party to pending until user accepts or rejects
            table.party = "Pending"
            table.save()

            # # Assign table party the new name
            # table.party = new_party.name
            # # Initialize seated time
            # table.time_seated = datetime.now(tz)
            # # Save new Table object
            # table.save()
            # # Delete off the waitlist
            # new_party.delete()
            print("Assigned Party {} to table {}".format(table.party, table.number))
