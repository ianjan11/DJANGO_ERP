from .settings import settings_view
from .company import (get_empty_company_form, company_list, company_details,
                      company_edit_view, company_create_view)
from .tenants import tenant_create_view, tenants_list_view, tenant_details, get_tenant_form, user_profile_update

from .partners import  (create_partner_view, get_vendors_view, get_customers_view, partners_details_view,
                        edit_partner_view, get_empty_partner_form, get_all_partners
                        )
