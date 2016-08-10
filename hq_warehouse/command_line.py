#!/usr/bin/env python3

import os, sys, getopt, datetime, re, decimal
from pytz import timezone

# Importing static exceptions is alright, even before django.setup()
from django.db import IntegrityError


# A trivial memory cache.  In the real world we should use memcached or redis
# since those can purge records if the cache is too big.  For our purposes we
# are ignoring the fact that the cache needs to be purged from time to time and
# inserting *all* dimension records we come across.  We know the size of the
# dimension tables, therefore it is very unlikely that we will end out of
# memory.
#
# This cache allows the database to use its own cache only for the inserts,
# this should make inserts quicker, notably inserts of offers:
#
# *   When checking the validity of an offer we only need to go to the database
#     if we do not find the required foreign keys in the cache.
#
# *   The database still needs to crosscheck the foreign keys but it can do so
#     using the index in the dimension table.  And only load the index of the
#     dimension table into its own cache, not the data itself.
CURRENCY = {}
FOREX = {}
CURRENCY_USD = None

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

def warehouse_start(stage_object, batch=None):
    '''
    Keep track of the staging are row when inserting into the warehouse.
    '''
    warehouse_object = {}
    if batch:
        warehouse_object['batch_id'] = batch.id
    else:
        warehouse_object['batch_id'] = stage_object.batch.id
    warehouse_object['origin_id'] = stage_object.id
    return warehouse_object


def stage_error(object, fields_in_error=None):
    '''
    Mark the object in the staging area as being in error, i.e. that it was
    attempted to be added to the warehouse but it was not possible.
    '''
    if fields_in_error:
        object.fields_in_error = ', '.join(fields_in_error)
    else:
        object.fields_in_error = 'Validation Errors'
    object.in_error = True
    object.processed = True
    object.save()
    return object

def dict_with_fields(org_dict, fields):
    new_dict = {}
    for f in fields:
        if f in org_dict:
            new_dict[f] = org_dict[f]
        else:
            return {}
    return new_dict

def save_to_warehouse(model, wparams):
    '''
    Try saving the record into the warehouse.  If things go well return it,
    otherwise return None.

    If a record in the staging area has the same values as a unique index of a
    record already in the warehouse consider that it is a duplicate.  And just
    ignore the fact that it was uploaded twice to the staging area.

    Ignoring duplicate transactions is the basis for any system that may need
    to be distributed across several machines.
    '''
    try:
        wobj = model(**wparams)
        wobj.save()
        return wobj
    except IntegrityError:
        # Now, this is tricky.  We might have hit *any* integrity error: not
        # null, foreign keys or uniqueness.  We need to ignore errors from
        # uniqueness so we check for those by trying to get the object from the
        # database and ignoring the error if we can do it.
        pass
    except decimal.InvalidOperation as e:
        # The Forex went overboard, we have Infinity or division by zero which,
        # after rounding, made some crazy billions of dollars or something
        # too close to zero.  Whatever it is it cannot be a sane price, error.
        return None

    # If every staging are object is fine then things go quickly, but if we
    # have a lot of dirty data and duplicates things follow below.  And the
    # below code hits a lot of database indexes/constraints, therefore is
    # rather slow.
    #
    # Extra note: This uses `_unique` which is a django internal, this code may
    # break in new revisions of django.
    uniqf = [ [x.name]
              for x in model._meta.get_fields()
              if hasattr(x, '_unique') and x._unique ]
    uniques = list(model._meta.unique_together) + uniqf
    for uniq in uniques:
        uniq_params = dict_with_fields(wparams, uniq)
        if not uniq_params:
            # Something very bad happened, we do not have unique fields for
            # this record.  The staging are record is definitely wrong.
            return None
        try:
            wobj = model.objects.get(**uniq_params)
            # It did not blow up!  Fine!  This is a duplicate, return it.
            return wobj
        except model.DoesNotExist:
            pass
    return None

def check_finalise(sobj, model, wparams, fields_in_error):
    '''
    Decide what to do with the staging record.
    '''
    if fields_in_error:
        stage_error(sobj, fields_in_error)
        # don't bother trying to save anything in the warehouse
        return None
    saved = save_to_warehouse(model, wparams)
    if saved:
        sobj.in_error = False
        sobj.fields_in_error = None
        sobj.processed = True
        sobj.save()
        return saved
    else:
        stage_error(sobj, fields_in_error)
    return None

def get_currency(id, wmod):
    '''
    Cache manager for the CURRENCY trivial cache.
    '''
    global CURRENCY
    if id in CURRENCY:
        return CURRENCY[id]
    else:
        try:
            currency = wmod.Currency.objects.get(id=id)
        except wmod.Currency.DoesNotExist:
            return None
        add_currency_cache(currency)
    return currency

def add_currency_cache(currency):
    '''
    This may save us from making an extra query for USD during forex.  A simple
    comparison, even if made hundreds of times shall be faster than opening a
    new database connection.
    '''
    global CURRENCY
    global CURRENCY_USD
    CURRENCY[currency.id] = currency
    if not CURRENCY_USD and 'USD' == currency.code:
        CURRENCY_USD = currency

def get_forex(key, wmod):
    '''
    Cache manager for the FOREX cache.

    Try very hard to get a decent forex:

    *   First try the cache
    *   If that fails try to find in the database
    *   If no such forex is in the database use the most recent forex between
        the two currencies.  That's not perfect, but better than nothing.
    '''
    global FOREX
    if key in FOREX:
        forex = FOREX[key]
    else:
        curr_from, curr_to, date_valid = key.split(':')
        cf = get_currency(int(curr_from), wmod)
        ct = get_currency(int(curr_to), wmod)
        dv = datetime.datetime.strptime(date_valid, '%Y-%m-%d').date()
        try:
            forex = wmod.Forex.objects.get( currency_from=cf
                                          , currency_to=ct
                                          , date_valid=dv
                                          )
        except wmod.Forex.DoesNotExist:
            forex = None
        try:
            q = wmod.Forex.objects.filter( currency_from=cf
                                         , currency_to=ct
                                         )
            forex = q.order_by('-date_valid').first()
        except wmod.Forex.DoesNotExist:
            forex = None
        if forex:
            add_forex_cache(forex)
    return forex

def add_forex_cache(forex):
    '''
    The forex cache is more complicated because we need to perform lookups in
    it based on what we have in the Offer model in the staging area.  Using
    memcached or redis would allow for a SQL like query, in the real world a
    real in-memory database should be used.
    '''
    global FOREX
    key = ''
    key += str(forex.currency_from.id)
    key += ':'
    key += str(forex.currency_to.id)
    key += ':'
    key += forex.date_valid.strftime('%Y-%m-%d')
    FOREX[key] = forex

def apnde(err_list, err):
    '''
    Error list append, since we may hit the same error several times during
    cleansing, only append it once to the list.
    '''
    if not err in err_list:
        err_list.append(err)
    return err_list

def match_pass(data, regex):
    r = re.compile(regex)
    match = r.search(data)
    if match:
        match = match.group()
    return match

def checkout_currency(sobj, smod, wmod, settings, batch=None):
    '''
    Checking a field for correct data and then placing it into the analogous
    field in the warehouse can certainly be done in several clever ways.  But
    all code is always three times harder to debug than it is to write, and
    data matching code will break and will need to be debugged.  Bad incoming
    data often breaks the sanity of even the most careful programmer.

    The code in the specific checkout_* functions will be changed and debugged
    often.  It is wiser to keep it simple and stupid, even if that means a lot
    of duplicated code.
    '''
    wparams = warehouse_start(sobj, batch)
    fields_in_error = []

    # Three uppercase characters
    data = match_pass(sobj.currency_code, r'^[A-Z]{3}$')
    if data:
        wparams['code'] = data
    else:
        apnde(fields_in_error, 'currency_code')

    # At least one meaningful character
    data = match_pass(sobj.currency_name, r'[A-Za-z0-9]')
    if data:
        wparams['name'] = sobj.currency_name.strip()
    else:
        apnde(fields_in_error, 'currency_name')

    wobj = check_finalise(sobj, wmod.Currency, wparams, fields_in_error)
    if wobj:
        add_currency_cache(wobj)
    return wobj

def checkout_forex(sobj, smod, wmod, settings, batch=None):
    '''
    Checking the Forex table requires the use of the CURRENCY cache, this makes
    mixed batches load faster into the warehouse since we already have the
    cache from loading the currencies.
    '''
    wparams = warehouse_start(sobj, batch)
    fields_in_error = []

    # Should be a valid currency
    data = match_pass(sobj.primary_currency_id, r'^\d+$')
    curr = None
    if data:
        curr = get_currency(int(data), wmod)
    if curr:
        wparams['currency_from'] = curr
    else:
        apnde(fields_in_error, 'primary_currency_id')

    # And another valid currency
    data = match_pass(sobj.secondary_currency_id, r'^\d+$')
    curr = None
    if data:
        curr = get_currency(int(data), wmod)
    if curr:
        wparams['currency_to'] = curr
    else:
        apnde(fields_in_error, 'secondary_currency_id')

    # We have no timezone info, so we cannot localize the date
    data = match_pass(sobj.date_valid, r'^\d{4}-\d{2}-\d{2}$')
    if data:
        dv = datetime.datetime.strptime(data, '%Y-%m-%d').date()
        wparams['date_valid'] = dv
    else:
        apnde(fields_in_error, 'date_valid')

    # An integer (1) or a (very simple) float
    data = match_pass(sobj.currency_rate, r'^(\d+|\d+\.\d+)$')
    if data:
        wparams['rate'] = float(data)
    else:
        apnde(fields_in_error, 'currency_rate')

    wobj = check_finalise(sobj, wmod.Forex, wparams, fields_in_error)
    if wobj:
        add_forex_cache(wobj)
    return wobj

def checkout_offer(sobj, smod, wmod, settings, batch=None):
    '''
    Offer loading uses both caches (CURRENCY and FOREX), and it has an extra
    twist since an offer from the staging area can be loaded either into Valid
    Offer or Invalid Offer based on a flag.  This makes the valid_offer flag
    the most important field to be verified, since we do not know where to
    attempt an insert if we cannot parse that field.
    '''
    global CURRENCY_USD
    wparams = warehouse_start(sobj, batch)
    fields_in_error = []

    # An integer
    data = match_pass(sobj.hotel_id, r'^\d+$')
    if data:
        wparams['hotel_id'] = data
    else:
        apnde(fields_in_error, 'hotel_id')

    # Integer or simple float (also, no zero or negative prices)
    data = match_pass(sobj.selling_price, r'^(\d+|\d+\.\d+)$')
    if data and 0.0 < float(data):
        wparams['original_price'] = float(data)
    else:
        apnde(fields_in_error, 'selling_price')

    # Integer, an ID
    data = match_pass(sobj.currency_id, r'^\d+$')
    curr = None
    if data:
        curr = get_currency(int(data), wmod)
    if curr:
        wparams['original_currency'] = curr
    else:
        apnde(fields_in_error, 'currency_id')

    # A flag, where -1 is false
    data = match_pass(sobj.breakfast_included_flag, r'^-?\d$')
    if data:
        wparams['breakfast_included'] = -1 != int(data)
    else:
        apnde(fields_in_error, 'breakfast_included_flag')

    # Date into date, again no timezone info
    data = match_pass(sobj.checkin_date, r'^\d{4}-\d{2}-\d{2}$')
    if data:
        dt = datetime.datetime.strptime(data, '%Y-%m-%d').date()
        wparams['checkin_date'] = dt
    else:
        apnde(fields_in_error, 'checkin_date')

    # And one more date
    data = match_pass(sobj.checkout_date, r'^\d{4}-\d{2}-\d{2}$')
    if data:
        dt = datetime.datetime.strptime(data, '%Y-%m-%d').date()
        wparams['checkout_date'] = dt
    else:
        apnde(fields_in_error, 'checkout_date')

    # Next we need to build a couple of fields from timestamps,
    # which is slightly more complicated.

    # Date and time from a timestamp (we have a time, should use timezones)
    data = match_pass(
        sobj.offer_valid_from
        , r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$'
        )
    if data:
        dtf = datetime.datetime.strptime(data, '%Y-%m-%d %H:%M:%S')
        tzn = timezone(settings.TIME_ZONE)
        loc = tzn.localize(dtf)
        wparams['valid_from_date'] = loc.date()
        wparams['valid_from_time'] = loc.time()
    else:
        apnde(fields_in_error, 'offer_valid_from')

    # And another date and time
    data = match_pass(
        sobj.offer_valid_to
        , r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$'
        )
    if data:
        dtt = datetime.datetime.strptime(data, '%Y-%m-%d %H:%M:%S')
        tzn = timezone(settings.TIME_ZONE)
        loc = tzn.localize(dtt)
        wparams['valid_to_date'] = loc.date()
        wparams['valid_to_time'] = loc.time()
    else:
        apnde(fields_in_error, 'offer_valid_to')

    # Now we need to perform forex conversion to populate the price in USD,
    # this can fail in several ways, therefore is rather tricky.  We use the
    # check-in date to find the forex because it is sensible for a warehouse
    # that process data in the past.  This does not make sense for a real-time
    # system and probably not much sense for the data mart, but a warehouse
    # should not care about what reads its data, it should be self contained.
    if CURRENCY_USD:
        cur_t = CURRENCY_USD
    else:
        try:
            cur_t = wmod.Currency.objects.get(code='USD')
        except wmod.Currency.DoesNotExist:
            cur_t = None
        CURRENCY_USD = cur_t
    cur_f = wparams.get('original_currency')
    datev = wparams.get('checkin_date')
    org_p = wparams.get('original_price')
    forex = None
    if cur_t and cur_f and datev and org_p:
        key = []
        key.append(str(cur_f.id))
        key.append(str(cur_t.id))
        key.append(datev.strftime('%Y-%m-%d'))
        forex = get_forex(':'.join(key), wmod)
    if cur_f and CURRENCY_USD.code == cur_f.code:
        # Check the currency code, just in case.
        # If it matches there is no need for forex
        wparams['price_usd'] = org_p
    elif forex:
        wparams['price_usd'] = decimal.Decimal(org_p) * forex.rate
    else:
        apnde(fields_in_error, 'currency_id')
        apnde(fields_in_error, 'selling_price')
        apnde(fields_in_error, 'checkin_date')

    # And this is even trickier.  We parsed the staging are record and,
    # if it is fine, we need to add it to the warehouse.  Yet, the warehouse
    # has two tables to add to, Valid Offer and Invalid Offer.  We need to
    # check the flag in the staging area and, from that, select the warehouse
    # table.
    data = match_pass(sobj.valid_offer_flag, r'^-?\d+$')
    if data:
        if -1 == int(data):
            offer_model = wmod.InvalidOffer
        else:
            offer_model = wmod.ValidOffer
            wparams['invalid'] = False
    else:
        apnde(fields_in_error, 'valid_offer_flag')

    wobj = check_finalise(sobj, offer_model, wparams, fields_in_error)
    return wobj

def print_info(sobj, wobj, verbose=False):
    '''
    Make the message printing consistent across different calls.
    '''
    if wobj and verbose:
        print( 'SUCCESS', sobj.__class__.__name__, str(sobj)
             , '=>',      wobj.__class__.__name__, str(wobj)
             )
    elif not wobj:
        print('FAILURE', sobj.__class__.__name__, str(sobj))
    # else stay silent

def checkout_batch():
    '''
    Set up the needed environment, scrutinise the parameters, and, if
    everything went alright call the actual function that will take the batch
    from the staging area and into he warehouse.
    '''
    settings_path()
    import django
    django.setup()
    from django.conf import settings
    from hq_stage import models as smod
    from hq_warehouse import models as wmod

    usage = 'hqw-checkout-batch [-hv] -b <batch number>'
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hvb:')
    except getopt.GetoptError as e:
        print(e)
        print(usage)
        sys.exit(2)
    batchno = None
    verbose = False
    for o, a in opts:
        if '-h' == o:
            print(usage)
            sys.exit(0)
        elif '-b' == o:
            batchno = a
        elif '-v' == o:
            verbose = True
        else:
            assert False, 'unhandled option [%s]' % o
    if not batchno:
        print(usage)
        sys.exit(1)
    try:
        batch = smod.Batch.objects.get(id=batchno)
    except smod.Batch.DoesNotExist:
        print('%s : no such batch number')
        exit(1)
    if batch.processed:
        print('WARNING: Processing again a batch that has been processed')
    # We use iterators so we do not need to load everything in memory,
    # moreover since we already have a memory cache.
    for currency in batch.currency_set.all():
        wobj = checkout_currency(currency, smod, wmod, settings, batch)
        print_info(currency, wobj, verbose)
    for exchange in batch.exchangerate_set.all():
        wobj = checkout_forex(exchange, smod, wmod, settings, batch)
        print_info(exchange, wobj, verbose)
    for offer in batch.offer_set.all():
        wobj = checkout_offer(offer, smod, wmod, settings, batch)
        print_info(offer, wobj, verbose)
    batch.processed = True
    batch.save()

def checkout_table():
    '''
    Perform a search through the entire table in the staging area, this will
    likely be slow.  Yet, it is an alternative to batch-by-batch loading.

    This only attempts to load rows that are in error and that error has not
    been set to an ignored error by an operator, i.e.

    SELECT * FROM <table> WHERE in_error = 1 AND ignore = 0;
    '''
    settings_path()
    import django
    django.setup()
    from django.conf import settings
    from hq_stage import models as smod
    from hq_warehouse import models as wmod

    tables = {
          'currency' : {
              'set' : smod.Currency
            , 'fun' : checkout_currency
            }
        , 'forex' : {
              'set' : smod.ExchangeRate
            , 'fun' : checkout_forex
            }
        , 'offer' : {
              'set' : smod.Offer
            , 'fun' : checkout_offer
            }
        }
    usage = 'hqw-checkout-table [-hv] -t <table>'
    try:
        opts, args = getopt.getopt(sys.argv[1:], 'hvt:')
    except getopt.GetoptError as e:
        print(e)
        print(usage)
        sys.exit(2)
    table = None
    verbose = False
    for o, a in opts:
        if '-h' == o:
            print(usage)
            sys.exit(0)
        elif '-t' == o:
            table = a
        elif '-v' == o:
            verbose = True
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

    qs = tables[table]['set'].objects.filter(in_error=True, ignore=False)
    for object in qs:
        wobj = tables[table]['fun'](object, smod, wmod, settings)
        print_info(object, wobj, verbose)

