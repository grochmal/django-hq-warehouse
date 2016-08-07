from django.db import models
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _
from django.conf import settings

import datetime
from pytz import timezone


class Origin(models.Model):
    '''
    Keep the log of the origin of this row.
    '''
    batch_id = models.BigIntegerField(
          _('batch id')
        , editable=False
        , db_index=True
        , help_text=_('original batch of data load')
        )
    origin_id = models.BigIntegerField(
          _('origin id')
        , editable=False
        , help_text=_('id of original item in the stage database')
        )
    insert_date = models.DateTimeField(
          _('insert date')
        , blank=True
        , editable=False
        , help_text=_('insert timestamp of this row in the warehouse')
        )

    def save(self, *args, **kwargs):
        if self.pk is None:  # this is an insert
            tz = timezone(settings.TIME_ZONE)
            self.insert_date = tz.localize(datetime.datetime.now())
        super(Origin, self).save(*args, **kwargs)

    class Meta:
        abstract = True


class Currency(Origin):
    '''
    The Currency only needs to be indexed by id.
    '''
    code = models.CharField(
          _('code')
        , max_length=3
        , unique=True
        , help_text=_('iso 4217 currency code')
        )
    name = models.CharField(
          _('name')
        , max_length=64
        , help_text=_('plain text name of the currency')
        )

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('hq_warehouse:currency', kwargs={ 'pk' : self.id })

    class Meta:
        verbose_name = _('currency')
        verbose_name_plural = _('currencies')


class Forex(Origin):
    '''
    Foreign Exchange Rates, these need to be heavily indexed for quicker
    searches.  The indexes impact insert time but that shall no hinder us too
    much since there are not that many rows.
    '''
    currency_from = models.ForeignKey(
          Currency
        , verbose_name=_('currency from')
        , related_name='forex_from'
        , help_text=_('currency from which the exchange is made')
        )
    currency_to = models.ForeignKey(
          Currency
        , verbose_name=_('currency to')
        , related_name='forex_to'
        , help_text=_('currency to which the exchange is made')
        )
    date_valid = models.DateField(
          _('date valid')
        , help_text=_('date for which this rate can be applied')
        )
    rate = models.DecimalField(
          _('exchange rate')
        , max_digits=20
        , decimal_places=10
        )

    def __str__(self):
        return ( self.currency_from.name
               + ' -> '
               + self.currency_to.name
               + ' @ '
               + str(self.date_valid)
               )

    def get_absolute_url(self):
        return reverse('hq_warehouse:forex', kwargs={ 'pk' : self.id })

    class Meta:
        unique_together = [ ( 'currency_from'
                            , 'currency_to'
                            , 'date_valid' ) ]
        index_together = [ ( 'currency_from' , 'currency_to' ) ]
        verbose_name = _('foreign exchange rate')
        verbose_name_plural = _('foreign exchange rates')


class Offer(Origin):
    '''
    To make smaller indexes we separate the valid from/to fields into date and
    time fields.  A date type is half the size of a timestamp, and since we
    will not be uploading data to a data mart we only care about the date part.

    The data mart itself will need to figure out the validity of the offer in
    the middle of a day.  But then again, only the data mart knows at which
    time a request comes to it.
    '''
    hotel_id = models.PositiveIntegerField(
          _('hotel id')
        , help_text=_('the hotel providing the offer')
        )
    price_usd = models.DecimalField(
          _('prince in usd')
        , max_digits=20
        , decimal_places=10  # leave extra resolution for forex
        , help_text=_('price converted to american dollars')
        )
    original_price = models.DecimalField(
          _('original price')
        , max_digits=20
        , decimal_places=10  # the original file has 13 sometimes!
        , help_text=_('original price of the offer')
        )
    original_currency = models.ForeignKey(
          Currency
        , verbose_name=_('original currency')
        , related_name='%(class)s_set'
        , help_text=_('currency of the original price')
        )
    breakfast_included = models.BooleanField(
          _('breakfast included')
        , help_text=_('whether breakfast is included in the price')
        )
    valid_from_date = models.DateField(
          _('valid from date')
        # we need an index here to mark valid offers when the day arrives
        , db_index=True
        , help_text=_('date from which this offer is valid')
        )
    valid_to_date = models.DateField(
          _('valid to date')
        # and an index here to mark offers that become invalid with time
        , db_index=True
        , help_text=_('date when this offer becomes invalid')
        )
    valid_from_time = models.TimeField(
          _('valid from time')
        , help_text=_('time of the day this offer becomes valid')
        )
    valid_to_time = models.TimeField(
          _('valid to time')
        , help_text=_('time of day this offer becomes invalid')
        )
    checkin_date = models.DateField(
          _('check-in date')
        , help_text=_('date the guest must check-in')
        )
    checkout_date = models.DateField(
          _('check-out date')
        , help_text=_('date the guest must check-out')
        )

    def __str__(self):
        return ( str(self.hotel_id)
               + ' @ '
               + self.valid_from_date.strftime('%Y%m%d%H%M')
               + ' - '
               + self.valid_to_date.strftime('%Y%m%d%H%M')
               )

    class Meta:
        abstract = True


class ValidOffer(Offer):
    '''
    Since offers are valid for a defined period of time they become invalid at
    a certain point.  This is the only update operation happening on this fact
    table, the update shall have no effect on queries against the warehouse but
    it may be very useful when extracting the data from the warehouse into data
    marts.

    The API calls are made towards the data mart, therefore we do not need
    indexes on the fields needed by the API query in the warehouse.  But we do
    need an index on the invalid field so the loading of the data mart can be
    made in a reasonable time.
    '''
    invalid = models.BooleanField(
          _('invalid')
        , db_index=True
        , default=False
        , help_text=_('marked when the offer becomes invalid')
        )

    def get_absolute_url(self):
        return reverse('hq_warehouse:valid', kwargs={ 'pk' : self.id })

    class Meta:
        unique_together = [ ( 'hotel_id'     , 'breakfast_included'
                            , 'checkin_date' , 'checkout_date'      ) ]
        verbose_name = _('valid offer')
        verbose_name_plural = _('valid offers')


class InvalidOffer(Offer):
    '''
    We might want old invalid offers for statistical queries.  If an offer is
    not valid anymore at the moment it is lifted from the staging area it will
    be placed in this table instead of the Valid Offer table.
    '''
    def get_absolute_url(self):
        return reverse('hq_warehouse:invalid', kwargs={ 'pk' : self.id })

    class Meta:
        unique_together = [ ( 'hotel_id'     , 'breakfast_included'
                            , 'checkin_date' , 'checkout_date'      ) ]
        verbose_name = _('invalid offer')
        verbose_name_plural = _('invalid offers')

