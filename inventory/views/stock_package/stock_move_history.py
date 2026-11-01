from datetime import timedelta
from decimal import Decimal
from django.core.paginator import Paginator
from django.db.models import Q, Count
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.cache import never_cache
from inventory.models import StockMove, Product

def stock_move_history(request, product_id):
    # aggregate on full queryset BEFORE paginating
    stock_moves = StockMove.objects.select_related(
        'product', 'warehouse', 'source_location', 'dest_location'
    ).all()
    product = get_object_or_404(Product, id=product_id)

    today = timezone.now().date()


    # — search
    search = request.GET.get('product_search')
    if search:
        stock_moves = stock_moves.filter(
            Q(product__name__icontains=search) |  # fixed: was passing queryset object
            Q(product__sku__icontains=search)
        )

    # — status
    move_status = request.GET.get('move_status')
    if move_status:
        stock_moves = stock_moves.filter(status=move_status)

    # — move type
    move_type = request.GET.get('move_type')
    if move_type:
        stock_moves = stock_moves.filter(move_type=move_type)

    # — date presets
    preset = request.GET.get('preset')
    target_date = request.GET.get('target_date')

    if target_date:
        # fixed: use __date= for DateTimeField comparison with a date string
        stock_moves = stock_moves.filter(created_at__date=target_date)
    elif preset == 'Today':
        stock_moves = stock_moves.filter(created_at__date=today)
    elif preset == 'ThisWeek':
        week_start = today - timedelta(days=today.weekday())
        stock_moves = stock_moves.filter(created_at__date__gte=week_start)
    elif preset == 'ThisMonth':
        stock_moves = stock_moves.filter(
            created_at__year=today.year,
            created_at__month=today.month
        )
    elif preset == 'ThisYear':
        stock_moves = stock_moves.filter(created_at__year=today.year)

    summary = stock_moves.aggregate(
        total_count    = Count('id'),
        draft_count  = Count('id', filter=Q(status='DRAFT')),
        waiting_count = Count('id', filter=Q(status='WAITING')),
        confirmed_count = Count('id', filter=Q(status='CONFIRMED')),
        partial_available_count = Count('id', filter=Q(status='PARTIALLY_AVAILABLE')),
        assigned_count = Count('id', filter=Q(status='ASSIGNED')),
        completed_count= Count('id', filter=Q(status='COMPLETED')),
        cancelled_count= Count('id', filter=Q(status='CANCELLED')),
    )

    paginator = Paginator(stock_moves, 15)
    page = request.GET.get('page')
    stock_moves_page = paginator.get_page(page)

    context = {
        'stock_moves': stock_moves_page,
        'summary'    : summary,
        'product': product,
    }

    if request.headers.get('HX-Request'):
        return render(
            request,
            'inventory/stock/partials/stock_components/stock_move_history.html',
            context
        )
    return render(request, 'inventory/stock/stock_details.html', context)




