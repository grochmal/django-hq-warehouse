#!/usr/bin/env python3

import os, sys, getopt, csv, datetime
from pytz import timezone

def settings_path():
    '''
    Before we can call django.setup() we need to know the path to the project
    configuration.  If we cannot find the configuration we can do nothing since
    we cannot even connect to the database.
    '''
    project_path = os.environ.get('HQ_DW_CONF_PATH')
    if not project_path:
        print( 'ERROR: You need to set HQ_DW_CONF_PATH environment variable '
             + 'to the path of the main django project (hq-dw).'
             )
        sys.exit(1)
    sys.path.append(project_path)
    settings = os.environ.get('DJANGO_SETTINGS_MODULE')
    if not settings:
        print( 'ERROR: You need to set DJANGO_SETTINGS_MODULE environment '
             + 'variable to the settings module in the main project (hq-dw).'
             )
        sys.exit(1)

def check_currency(models, settings):
    '''
    Bulk insert of the Currency model.

    Since we may have a lot of records being inserted firing an insert for each
    would not be quick enough in most wareouses.  Instead we use a bulk insert
    every a certain number of records.

    TODO: The number of records commited in bulk should be configurable.
    '''
    pass
    #fields = list(map(lambda x: x.name, models.Currency._meta.get_fields()))
    #ignore = list(map(lambda x: x.name, models.DataRow._meta.get_fields()))
    #ignore.append('id')
    #infields = diff_list(fields, ignore)

    #batch = models.Batch()
    #batch.save()
    #print('Using new batch [%i]' % batch.id)
    #commit_num = 3
    #commit_list = []
    #iter = read_unix_csv(csv_file)
    #next(iter, None)  # ignore header
    #next(iter, None)  # ignore dummy row
    ## bulk_create does not call save(), we need to add the date manually
    #tz = timezone(settings.TIME_ZONE)
    #insert_date = tz.localize(datetime.datetime.now())
    #for row in iter:
        #field_dict = zip_default(infields, row)
        ##print(field_dict)
        #cur = models.Currency(
              #batch=batch
            #, insert_date=insert_date
            #, **field_dict
            #)
        #commit_list.append(cur)
        #if len(commit_list) % commit_num == 0:
            #models.Currency.objects.bulk_create(commit_list)
            #print('commit', commit_num, 'currencies')
            #commit_list = []
    #models.Currency.objects.bulk_create(commit_list)
    #print('final commit, and we are done')

def check_exchange_rate(models, settings):
    pass

def check_offer(models, settings):
    pass

def check_table():
    '''
    Set up the needed environment, scrutinise the parameters, and, if
    everything went alright call the actual function that will load the table
    data from a file.

    We check that the file exists but it is the responsibility of the called
    function to verify if the file is in the correct format.
    '''
    settings_path()
    import django
    django.setup()
    from django.conf import settings
    from hq_stage import models

    tables = {
          'currency' : check_currency
        , 'forex' : check_forex
        , 'offer' : check_offer
        }

    usage = 'hqw-check-table [-h] -t <table>'
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hf:t:')
    except getopt.GetopetError as e:
        print(e)
        print(usage)
        sys.exit(2)
    table = None
    for o, a in opts:
        if '-h' == o:
            print(usage)
            sys.exit(0)
        elif '-t' == o:
            table = a
        else:
            assert False, 'unhandled option [%s]' % o
    if not table:
        print(usage)
        sys.exit(1)
    if not table in tables:
        print(usage)
        print('No such table to load.  Available tables:')
        print(', '.join(sorted(tables.keys())))
        sys.exit(1)

    tables[table](models, settings)

