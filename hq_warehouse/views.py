from django.views import generic

from . import models


class DocView(generic.TemplateView):
    template_name = 'hq_warehouse/doc.html'


class HqWarehouseListView(generic.ListView):
    template_name = 'hq_main/list.html'
    context_object_name = 'object_list'
    paginate_by = 12  # I just like the number 12


class CurrencyListView(HqWarehouseListView):
    model = models.Currency


class ForexListView(HqWarehouseListView):
    model = models.Forex


class ValidOfferListView(HqWarehouseListView):
    model = models.ValidOffer


class InvalidOfferListView(HqWarehouseListView):
    model = models.InvalidOffer


class CurrencyView(generic.DetailView):
    model = models.Currency
    template_name = 'hq_warehouse/currency.html'
    context_object_name = 'currency'


class ForexView(generic.DetailView):
    model = models.Forex
    template_name = 'hq_warehouse/forex.html'
    context_object_name = 'forex'


# For both valid and invalid offer tables we use the same template, since we do
# not care about the validity of the offer when we have no means of updating
# it.  To update a valid offer into an invalid one we use the update view
# below.
#
# To get to the update view from the list view we can use the link inside this
# view.  This is pretty bad design since it is logic inside a template and
# actually and should be changed, but for now it makes the code simpler.
class ValidOfferView(generic.DetailView):
    model = models.ValidOffer
    template_name = 'hq_warehouse/offer.html'
    context_object_name = 'offer'


class InvalidOfferView(generic.DetailView):
    model = models.InvalidOffer
    template_name = 'hq_warehouse/offer.html'
    context_object_name = 'offer'


class ValidOfferUpdateView(generic.edit.UpdateView):
    model = models.ValidOffer
    template_name = 'hq_warehouse/offer_update.html'
    context_object_name = 'offer'
    fields  = [ 'invalid' ]

