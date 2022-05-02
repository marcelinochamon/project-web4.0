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
            new_party = people
            return new_party
        elif 2<= table.seat-people.party <=3  and people.wait_time >= 15:
            new_party = people
            return new_party
        elif 4 <= table.seat-people.party <= 5 and people.wait_time >= 30:
            new_party = people
            return new_party
        elif table.seat-people.party >= 6 and people.wait_time >= 45:
            new_party = people
            return new_party
        if people == waiting_people[-1]:
            return None 


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
