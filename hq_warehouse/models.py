from django.db import models
from django.core.urlresolvers import reverse
from django.utils.translation import ugettext_lazy as _
from django.conf import settings

import datetime
from pytz import timezone


class Origin(models.Model):
    batch_id = models.BigIntegerField(
          _('batch_id')
        , editable=False
        , index=True
        , help_text=_('original batch of data load')
        )
    origin_id = models.BigIntegerField(
          _('origin_id')
        , editable=False
        , help_text=_('id of original item in the stage database')
        )
    insert_date = models.DateTimeField(
          _('insert date')
        , blank=True
        , editable=False
        , help_text=_('insert timestamp of this row in the warehouse')
        )

    class Meta:
        abstract = True


class Currency(Origin):
    code = models.CharField(
          _('code')
        , max_length=3
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
    exchange_rate = models.Decimal(
          max_digits=9
        , decimal_places=6
        )

    def __str__(self):
        return ( self.currency_from.name
               + ' -> '
               + self.currency.to
               + ' @ '
               + str(self.date_valid)
               )

    def get_absolute_url(self):
        return reverse('hq_warehouse:forex', kwargs={ 'pk' : self.id })

    class Meta:
        index_together = [
              ( 'currency_from' , 'currency_to' )
            , ( 'currency_from' , 'currency_to' , 'date_valid' )
            ]
        verbose_name = _('foreign exchange rate')
        verbose_name_plural = _('foreign exchange rates')


class Offer(Origin):
    hotel_id = models.PositiveIntegerField(
          _('hotel id')
        , help_text=_('the hotel providing the offer')
        )
    price_usd = models.Decimal(
          _('prince in usd')
        , max_digits=9
        , decimal_places=3  # leave extra resolution for forex
        , help_text=_('price converted to american dollars')
        )
    original_price = models.Decimal(
          _('original price')
        , max_digits=9
        , decimal_places=4  # some currencies may have 4 decimal places
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
    valid_from = models.DateTimeField(
          _('valid from date')
        , help_text=_('date from which this offer is valid')
        )
    valid_to = models.DateTimeField(
          _('valid to date')
        , help_text=_('date when this offer becomes invalid')
        )

    def __str__(self):
        return ( str(self.hotel_id)
               + ' @ '
               + self.valid_from.strftime('%Y%m%d%H%M')
               + ' - '
               + self.valid_to.strftime('%Y%m%d%H%M')
               )

    class Meta:
        abstract = True


class ValidOffer(Offer):
    '''
    Since offers are valid for a defined period of time they become invalid at
    a certain point.  This is the only update operation happening on this fact
    table, the update shall have no effect on queries against the warehouse but
    it may be very useful to extract the data from the warehouse into data
    marts.

    The unique constraint is a guess, the assignment argues that: check-in,
    check-out, source and breakfast flag are unique.  But at this point we do
    not have most of that data.  The guess is that:

    hotel_id   == source
    valid_from == check-in
    valid_to   == check-out
    '''
    invalid = models.BooleanField(
          _('invalid')
        , index=True
        , help_text=_('marked when the offer becomes invalid')
        )

    def get_absolute_url(self):
        return reverse('hq_warehouse:valid', kwargs={ 'pk' : self.id })

    class Meta:
        index_together = [
              ( 'hotel_id' , 'valid_from' )
            , ( 'hotel_id' , 'valid_to'   )
            ]
        unique_together = ( 'hotel_id'   , 'breakfast_included'
                          , 'valid_from' , 'valid_to'           )
        verbose_name = _('valid offer')
        verbose_name_plural = _('valid offers')


class InvalidOffer(Offer):
    '''
    We might want old invalid offers for statistical queries.  If an offer is
    not valid anymore at the moment it is lifted from the stage area it will
    be placed in this table instead of the Valid Offer table.
    '''
    def get_absolute_url(self):
        return reverse('hq_warehouse:invalid', kwargs={ 'pk' : self.id })

    class Meta:
        index_together = [
              ( 'hotel_id' , 'valid_from' )
            , ( 'hotel_id' , 'valid_to' )
            ]
        unique_together = ( 'hotel_id'   , 'breakfast_included'
                          , 'valid_from' , 'valid_to'           )
        verbose_name = _('invalid offer')
        verbose_name_plural = _('invalid offers')


# I'll move the following tables to the data mart

class Hour(models.Model):
    '''
    Pre-populated date and hour table, used for cross-linking with the Hotel
    Offer table.  This table is not needed in the warehouse it is needed in a
    data mart where it is used as a window cache for user queries.
    '''
    day = models.DateField(
          _('day')
        , help_text=_('the day for links')
        )
    hour = models.PositiveSmallIntegerField(
          _('hour')
        , help_text=_('the hour of the day')
        )

    def __str__(self):
        return str(self.day) + '@' + ('%02i' % self.hour)

    def get_absolute_url(self):
        return reverse('hq_warehouse:hour', kwargs={ 'pk' : self.id })

    class Meta:
        index_together = [ ( 'day' , 'hour' ) ]
        verbose_name = _('hour')
        verbose_name_plural = _('hours')


class HotelOffer(models.Model):
    '''
    This is heavily modified from the assignment, since the uniqueness
    condition in there (check-in, check-out, source, breakfast) has long been
    lost (check-in and check-out only exist in the staging area).

    Instead of making a single flag for the existence of an offer, we link the
    offers.  And, instead of populating this table for all hours we put the
    date-hour pair in their own table (Hour).  This way we can walk the Hour
    table and join against all available offers for the period.

    This is not the type of query that needs to be performed in a warehouse,
    this table is needed for data marts to copy from.
    '''
    hour = models.ForeignKey(
          Hour
        , verbose_name=_('hour')
        , related_name='hotel_offer'
        , help_text=_('hour on which this offer is valid')
        )
    # the hotel_id is here so we can make a better index
    hotel_id = models.PositiveIntegerField(
          _('hotel id')
        , help_text=_('the hotel providing the offer')
        )
    offer_id = models.ForeignKey(
          ValidOffer
        , verbose_name=_('offer')
        , related_name='offer_hours'
        , help_text=_('')
        )

