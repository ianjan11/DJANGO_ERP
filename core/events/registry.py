def register_all():

    from sales.events.subscribers import register_handlers as register_sales_handlers


    register_sales_handlers()
