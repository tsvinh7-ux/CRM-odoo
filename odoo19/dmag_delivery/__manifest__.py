{
    'name': 'DMAG Triển khai dịch vụ',
    'version': '19.0.1.0.0',
    'category': 'Services/Project',
    'summary': 'Lộ trình triển khai theo đơn kê: tự học & học có hướng dẫn (eLearning), '
               'kèm 1:1 (lịch + biên bản), thực địa (Project Sprint); cờ Pulse; DDA lần 2',
    'author': 'DMAG',
    'license': 'LGPL-3',
    'depends': ['dmag_dda', 'website_slides', 'project', 'calendar'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/dmag_delivery_plan_views.xml',
        'views/dmag_delivery_session_views.xml',
        'views/product_views.xml',
        'views/res_partner_views.xml',
        'views/sale_order_views.xml',
        'views/dmag_delivery_menus.xml',
    ],
    'demo': [
        'demo/dmag_delivery_demo.xml',
    ],
    'installable': True,
}
