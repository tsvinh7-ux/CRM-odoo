{
    'name': 'DMAG Hợp đồng & lịch thu',
    'version': '19.0.1.0.0',
    'category': 'Sales/Sales',
    'summary': 'Hợp đồng gắn lead / đơn bán / đơn kê, lịch thu nhiều đợt (40/40/20…), '
               'xuất hoá đơn từng đợt, theo dõi đã thu – công nợ – quá hạn, nhắc thu tự động',
    'author': 'DMAG',
    'license': 'LGPL-3',
    'depends': ['dmag_dda', 'sale_crm', 'account'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/ir_cron_data.xml',
        'views/dmag_contract_views.xml',
        'views/sale_order_views.xml',
        'views/dmag_contract_menus.xml',
    ],
    'demo': [
        'demo/dmag_contract_demo.xml',
    ],
    'installable': True,
}
