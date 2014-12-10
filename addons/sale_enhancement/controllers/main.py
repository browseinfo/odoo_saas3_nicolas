# -*- coding: utf-8 -*-
import random
import simplejson
import werkzeug

from openerp import SUPERUSER_ID
from openerp.addons.web import http
from openerp.addons.web.http import request
from openerp.tools.translate import _
from openerp.addons.website.models.website import slug

PPG = 20 # Products Per Page
PPR = 4  # Products Per Row

class table_compute(object):
    def __init__(self):
        self.table = {}

    def _check_place(self, posx, posy, sizex, sizey):
        res = True
        for y in range(sizey):
            for x in range(sizex):
                if posx+x>=PPR:
                    res = False
                    break
                row = self.table.setdefault(posy+y, {})
                if row.setdefault(posx+x) is not None:
                    res = False
                    break
            for x in range(PPR):
                self.table[posy+y].setdefault(x, None)
        return res

    def process(self, products):
        # Compute products positions on the grid
        minpos = 0
        index = 0
        maxy = 0
        for p in products:
            x = min(max(p.website_size_x, 1), PPR)
            y = min(max(p.website_size_y, 1), PPR)
            if index>PPG:
                x = y = 1

            pos = minpos
            while not self._check_place(pos%PPR, pos/PPR, x, y):
                pos += 1

            if index>PPG and (pos/PPR)>maxy:
                break

            if x==1 and y==1:   # simple heuristic for CPU optimization
                minpos = pos/PPR

            for y2 in range(y):
                for x2 in range(x):
                    self.table[(pos/PPR)+y2][(pos%PPR)+x2] = False
            self.table[pos/PPR][pos%PPR] = {
                'product': p, 'x':x, 'y': y,
                'class': " ".join(map(lambda x: x.html_class or '', p.website_style_ids))
            }
            if index<=PPG:
                maxy=max(maxy,y+(pos/PPR))
            index += 1

        # Format table according to HTML needs
        rows = self.table.items()
        rows.sort()
        rows = map(lambda x: x[1], rows)
        for col in range(len(rows)):
            cols = rows[col].items()
            cols.sort()
            x += len(cols)
            rows[col] = [c for c in map(lambda x: x[1], cols) if c != False]

        return rows

class sale_enhancement(http.Controller):
    _order = 'website_published desc, website_sequence desc'

    def get_attribute_ids(self):
        attributes_obj = request.registry['product.attribute']
        attributes_ids = attributes_obj.search(request.cr, request.uid, [], context=request.context)
        return attributes_obj.browse(request.cr, request.uid, attributes_ids, context=request.context)

    def get_pricelist(self):
        """ Shortcut to get the pricelist from the website model """
        return request.registry['website'].ecommerce_get_pricelist_id(request.cr, request.uid, None, context=request.context)

    def get_order(self):
        """ Shortcut to get the current ecommerce quotation from the website model """
        return request.registry['website'].ecommerce_get_current_order(request.cr, request.uid, context=request.context)

    def get_products(self, product_ids):
        product_obj = request.registry.get('product.template')
        request.context['pricelist'] = self.get_pricelist()
        # search for checking of access rules and keep order
        product_ids = [id for id in product_ids if id in product_obj.search(request.cr, request.uid, [("id", 'in', product_ids)], context=request.context)]
        return product_obj.browse(request.cr, request.uid, product_ids, context=request.context)

    def has_search_filter(self, attribute_id, value_id=None):
        if request.httprequest.args.get('filters'):
            filters = simplejson.loads(request.httprequest.args['filters'])
        else:
            filters = []
        for key_val in filters:
            if key_val[0] == attribute_id and (not value_id or value_id in key_val[1:]):
                return key_val
        return False

    @http.route([
        '/shop/category/<string:id>/<model("product.category"):category>/',
        '/shop/category/<string:id>/<model("product.category"):category>/page/<int:page>/',
    ], type='http', auth="public", website=True, multilang=True)
    def product_shop(self, category=None, id=None, page=0, filters='', search='', **post):
        cr, uid, context = request.cr, request.uid, request.context
        product_obj = request.registry.get('product.template')
        base_domain = request.registry.get('website').ecommerce_get_product_domain()
        domain = list(base_domain)
        if search:
            args_id = id.split('-')
            if len(args_id) > 1:
                domain += ['|',
                           ('name', 'ilike', search),
                           ('description', 'ilike', search), ('product_variant_ids.public_categ_id', 'child_of', int(args_id[-1]))]
			else:
				domain += ['|',
                           ('name', 'ilike', search),
                           ('description', 'ilike', search)]
        if category:
            domain.append(('categ_id', 'child_of', int(category)))
            if isinstance(category, (int,str,unicode)):
                category = request.registry.get('product.public.category').browse(cr, uid, int(category), context=context)
        
        if filters:
            filters = simplejson.loads(filters)
            if filters:
                ids = self.attributes_to_ids(cr, uid, filters)
                domain.append(('id', 'in', ids or [0]))

        #domain code for products
        pdomain = list(domain)
        if category:
            args_id = id.split('-')
            if len(args_id) > 1:
                pdomain.append(('product_variant_ids.public_categ_id', 'child_of', int(args_id[-1])))

        url = "/shop/"
        product_count = product_obj.search_count(cr, uid, pdomain, context=context)
        if search:
            post["search"] = search
        if filters:
            post["filters"] = filters
        if id:
            url = "/shop/category/%s/%s/" % (id, slug(category))

        pager = request.website.pager(url=url, total=product_count, page=page, step=PPG, scope=7, url_args=post)

        request.context['pricelist'] = self.get_pricelist()
        pids = product_obj.search(cr, uid, pdomain, limit=PPG+10, offset=pager['offset'], order=self._order, context=context)
        products = product_obj.browse(cr, uid, pids, context=context)

        # added code
        internal_categ_obj = request.registry.get('product.category')
        internal_categ_ids = internal_categ_obj.search(request.cr, request.uid, [], context=request.context)
        internal_categories = internal_categ_obj.browse(request.cr, request.uid, internal_categ_ids, context=request.context)
        internal_categs = filter(lambda x: not x.parent_id, internal_categories)

        styles = []
        try:
            style_obj = request.registry.get('product.style')
            style_ids = style_obj.search(request.cr, request.uid, [], context=request.context)
            styles = style_obj.browse(request.cr, request.uid, style_ids, context=request.context)
        except:
            pass

        category_obj = request.registry.get('product.public.category')
        category_ids = [product['public_categ_id'][0] for product in product_obj.read_group(cr, uid, domain, ['public_categ_id'], ['public_categ_id'], context=context) if product['public_categ_id']]
        categories = category_obj.browse(cr, uid, category_ids, context=context)
        all_categories = set(categories)
        for cat in categories:
            parent = cat.parent_id
            while parent:
                all_categories.add(parent)
                parent = parent.parent_id
        categories = list(all_categories)
        categories.sort(key=lambda x: x.sequence)

        if search:
            categories = []

        if len(filter(lambda x: not x.parent_id, categories)) == 0:
            domain = list(base_domain)
            domain.append(('categ_id', 'child_of', int(category)))
            category_ids = [product['public_categ_id'][0] for product in product_obj.read_group(cr, uid, domain, ['public_categ_id'], ['public_categ_id'], context=context) if product['public_categ_id']]
            categories = category_obj.browse(cr, uid, category_ids, context=context)
            all_categories = set(categories)
            for cat in categories:
                parent = cat.parent_id
                while parent:
                    all_categories.add(parent)
                    parent = parent.parent_id
            categories = list(all_categories)
            categories.sort(key=lambda x: x.sequence)

        ## breadcrumb code
        main_categ = None
        if len(args_id) > 1:
            ids = int(args_id[-1])
            main_categ = category_obj.browse(request.cr, request.uid, [ids], context=request.context)[0]
            all_categ_ids = category_obj.search(request.cr, request.uid, [], context=request.context)
            all_categ = category_obj.browse(request.cr, request.uid, all_categ_ids, context=request.context)
            bread_crumb = set()
            for categs in all_categ:
                if categs == main_categ:
                    parent = categs.parent_id
                    while parent:
                        bread_crumb.add(parent)
                        parent = parent.parent_id
            bread_crumb = list(bread_crumb)
            bread_crumb.sort(key=lambda x: x.id)
        else:
            all_categ_ids = category_obj.search(request.cr, request.uid, [], context=request.context)
            all_categ = category_obj.browse(request.cr, request.uid, all_categ_ids, context=request.context)
            bread_crumb = set()
            for categs in all_categ:
                if categs == category:
                    parent = category.parent_id
                    while parent:
                        bread_crumb.add(parent)
                        parent = parent.parent_id
            bread_crumb = list(bread_crumb)
            bread_crumb.sort(key=lambda x: x.id)

        #code for not list out categories which has no product
        sub_categories = filter(lambda x: x.parent_id, categories)
        sub_categ = []
        for sc in sub_categories:
            sub_categ.append(sc.id)

        values = {
            'products': products,
            'bins': table_compute().process(products),
            'rows': PPR,
            'range': range,
            'search': {
                'search': search,
                'category': category and int(category),
                'filters': filters,
            },
            'b_crumb': bread_crumb,
            'main_categ': main_categ,
            'pager': pager,
            'styles': styles,
            'category': category,
            'sub_categ' : sub_categ,
            'categories': filter(lambda x: not x.parent_id, categories),
            'int_categories': internal_categs,
            'all_categories': categories,
            'id':id,
            'Ecommerce': self,
            'style_in_product': lambda style, product: style.id in [s.id for s in product.website_style_ids],
        }
        return request.website.render("website_sale.products", values)


    @http.route([
        '/shop/',
        '/shop/page/<int:page>/',
        '/shop/category/<model("product.public.category"):category>/',
        '/shop/category/<model("product.public.category"):category>/page/<int:page>/'
    ], type='http', auth="public", website=True, multilang=True)
    def shop(self, category=None, id=None, page=0, filters='', search='', **post):
        cr, uid, context = request.cr, request.uid, request.context

        product_obj = request.registry.get('product.template')
        base_domain = request.registry.get('website').ecommerce_get_product_domain()
        domain = list(base_domain)
        if search:
            domain += ['|',
                ('name', 'ilike', search),
                ('description', 'ilike', search)]
        if category:
            domain.append(('product_variant_ids.public_categ_id', 'child_of', int(category)))
            if isinstance(category, (int,str,unicode)):
                category = request.registry.get('product.public.category').browse(cr, uid, int(category), context=context)

        if filters:
            filters = simplejson.loads(filters)
            if filters:
                ids = self.attributes_to_ids(cr, uid, filters)
                domain.append(('id', 'in', ids or [0]))

        url = "/shop/"
        product_count = product_obj.search_count(cr, uid, domain, context=context)
        if search:
            post["search"] = search
        if filters:
            post["filters"] = filters
        if category:
            url = "/shop/category/%s/" % slug(category)

        pager = request.website.pager(url=url, total=product_count, page=page, step=PPG, scope=7, url_args=post)

        request.context['pricelist'] = self.get_pricelist()

        pids = product_obj.search(cr, uid, domain, limit=PPG+10, offset=pager['offset'], order=self._order, context=context)
        products = product_obj.browse(cr, uid, pids, context=context)

        # added code
        internal_categ_obj = request.registry.get('product.category')
        internal_categ_ids = internal_categ_obj.search(request.cr, request.uid, [], context=request.context)
        internal_categories = internal_categ_obj.browse(request.cr, request.uid, internal_categ_ids, context=request.context)
        internal_categs = filter(lambda x: not x.parent_id, internal_categories)

        styles = []
        try:
            style_obj = request.registry.get('product.style')
            style_ids = style_obj.search(request.cr, request.uid, [], context=request.context)
            styles = style_obj.browse(request.cr, request.uid, style_ids, context=request.context)
        except:
            pass

        category_obj = request.registry.get('product.public.category')
        category_ids = [product['public_categ_id'][0] for product in product_obj.read_group(cr, uid, base_domain, ['public_categ_id'], ['public_categ_id'], context=context) if product['public_categ_id']]
        categories = category_obj.browse(cr, uid, category_ids, context=context)
        all_categories = set(categories)
        for cat in categories:
            parent = cat.parent_id
            while parent:
                all_categories.add(parent)
                parent = parent.parent_id
        categories = list(all_categories)
        categories.sort(key=lambda x: x.sequence)

        ## breadcrumb code
        all_categ_ids = category_obj.search(request.cr, request.uid, [], context=request.context)
        all_categ = category_obj.browse(request.cr, request.uid, all_categ_ids, context=request.context)
        bread_crumb = set()
        for categs in all_categ:
            if categs == category:
                parent = category.parent_id
                while parent:
                    bread_crumb.add(parent)
                    parent = parent.parent_id
        bread_crumb = list(bread_crumb)
        bread_crumb.sort(key=lambda x: x.id)
        
        #code for not list out categories which has no product
        sub_categories = filter(lambda x: x.parent_id, categories)
        sub_categ = []
        for sc in sub_categories:
            sub_categ.append(sc.id)

        values = {
            'products': products,
            'bins': table_compute().process(products),
            'rows': PPR,
            'range': range,
            'search': {
                'search': search,
                'category': category and int(category),
                'filters': filters,
            },
            'b_crumb': bread_crumb,
            'pager': pager,
            'styles': styles,
            'category': category,
            'categories': filter(lambda x: not x.parent_id, categories),
            'sub_categ' : sub_categ,
            'int_categories': internal_categs,
            'id':id,
            'all_categories': categories,
            'Ecommerce': self,   # TODO fp: Should be removed
            'style_in_product': lambda style, product: style.id in [s.id for s in product.website_style_ids],
        }
        return request.website.render("website_sale.products", values)

    @http.route(['/shop/product/<model("product.template"):product>/'], type='http', auth="public", website=True, multilang=True)
    def product(self, product, search='', category='', filters='', **kwargs):
        cr, uid, context = request.cr, request.uid, request.context

        base_domain = request.registry.get('website').ecommerce_get_product_domain()
        category_obj = request.registry.get('product.public.category')
        product_obj = request.registry.get('product.template')
        if category:
            category = category_obj.browse(cr, uid, int(category), context=context)

        category_ids = [prod['public_categ_id'][0] for prod in product_obj.read_group(cr, uid, base_domain, ['public_categ_id'], ['public_categ_id'], context=context) if prod['public_categ_id']]
        categories = category_obj.browse(cr, uid, category_ids, context=context)
        all_categories = set(categories)
        for cat in categories:
            parent = cat.parent_id
            while parent:
                all_categories.add(parent)
                parent = parent.parent_id
        categories = list(all_categories)
        categories.sort(key=lambda x: x.sequence)
        
        #code for not list out categories which has no product
        sub_categories = filter(lambda x: x.parent_id, categories)
        sub_categ = []
        for sc in sub_categories:
            sub_categ.append(sc.id)

        request.context['pricelist'] = self.get_pricelist()
        values = {
            'Ecommerce': self,
            'main_object': product,
            'product': product,
            'category': category,
            'categories': filter(lambda x: not x.parent_id, categories), # added this code
            'sub_categ' : sub_categ, # added this code
            'search': {
                'search': search,
                'category': category and int(category),
                'filters': filters,
            }
        }
        return request.website.render("website_sale.product", values)
