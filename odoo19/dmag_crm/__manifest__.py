{
    'name': 'DMAG CRM B2B',
    'version': '19.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Hồ sơ phòng khám 360°, phân khúc PK1–PK5, chặng G0–G5, DISC, '
               'cổng giai đoạn pipeline, suất triển khai theo quý',
    'author': 'DMAG',
    'license': 'LGPL-3',
    'depends': ['crm', 'sale_management', 'contacts'],
    'data': [
        'security/dmag_security.xml',
        'security/ir.model.access.csv',
        'data/dmag_segment_data.xml',
        'data/crm_team_stage_data.xml',
        'views/dmag_segment_views.xml',
        'views/dmag_capacity_views.xml',
        'views/res_partner_views.xml',
        'views/crm_stage_views.xml',
        'views/crm_lead_views.xml',
        'views/dmag_menus.xml',
    ],
    'demo': [
        'demo/dmag_crm_demo.xml',
    ],
    'application': True,
    'installable': True,
}
