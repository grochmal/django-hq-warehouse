from django.conf.urls import url

from . import views


app_name = 'hq_warehouse'
urlpatterns = [
      url( r'^currency/(?P<pk>\d+)/'
         , views.CurrencyView.as_view()
         , name='currency'
         )
    , url( r'^currency/$'
         , views.CurrencyListView.as_view()
         , name='currency_list'
         )
    , url( r'^forex/(?P<pk>\d+)/'
         , views.ForexView.as_view()
         , name='forex'
         )
    , url( r'^forex/$'
         , views.ForexListView.as_view()
         , name='forex_list'
         )
    , url( r'^valid-offer/(?P<pk>\d+)/'
         , views.ValidOfferView.as_view()
         , name='valid'
         )
    , url( r'^valid-offer/$'
         , views.ValidOfferListView.as_view()
         , name='valid_list'
         )
    , url( r'^invalid-offer/(?P<pk>\d+)/'
         , views.InvalidOfferView.as_view()
         , name='invalid'
         )
    , url( r'^invalid-offer/$'
         , views.InvalidOfferView.as_view()
         , name='invalid_list'
         )
    , url( r'^offer-update/(?P<pk>\d+)/'
         , views.ValidOfferUpdateView.as_view()
         , name='update'
         )
]

