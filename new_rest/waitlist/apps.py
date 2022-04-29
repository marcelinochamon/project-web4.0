from django.apps import AppConfig
import schedule
import time
from datetime import datetime
from django.utils import timezone
import threading
from django.db.backends.signals import connection_created



class WaitlistConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'waitlist'

    # Gets called after Django boots up
    def ready(self):
        tz = timezone.get_default_timezone()
        from .models import Table, Wait
        def start_thread(**kwargs):
            def scheduler():
                def assign_tables():
                    print("I worked")
                    empty_tables = Table.objects.filter(party = "Empty")
                    waiting_people = Wait.objects.all().order_by("arrival_time")
                    print(empty_tables)
                    # for table in empty_tables:
                    #     print(len(table))
                    #     if len(waiting_people) == 0:
                    #         print("I want to break")
                    #         # break
                    #     else:
                    #         print("I made it here")
                    #         # new_party = waiting_people.pop()
                    #         # table.party = new_party.name
                    #         # table.time_seated = datetime.now(tz)
                    #         # table.save()
                    #         # new_party.delete()
    

                schedule.every(2).seconds.do(assign_tables)
                while True:
                    schedule.run_pending()
                    time.sleep(2)
            t = threading.Thread(target = scheduler, kwargs = {})
            t.setDaemon(True)
            t.start()

        # connection_created.connect(start_thread)


