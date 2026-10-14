{
    'name': 'DMAG DDA & Đơn kê lộ trình',
    'version': '17.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Kiểm toán DDA 10 trụ cột, Radar 4 lớp, phân luồng PK/G, '
               'đơn kê lộ trình module × hình thức, tạo báo giá',
    'author': 'DMAG',
    'license': 'LGPL-3',
    'depends': ['dmag_crm', 'sale_management', 'sale_crm'],
    'data': [
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'data/dmag_pillar_data.xml',
        'data/product_data.xml',
        'data/crm_stage_gate_data.xml',
        'report/dmag_dda_report.xml',
        'views/dmag_pillar_views.xml',
        'views/dmag_dda_audit_views.xml',
        'views/dmag_prescription_views.xml',
        'views/product_views.xml',
        'views/crm_lead_views.xml',
        'views/res_partner_views.xml',
        'views/dmag_dda_menus.xml',
    ],
    'demo': [
        'demo/dmag_dda_demo.xml',
    ],
    'installable': True,
}
