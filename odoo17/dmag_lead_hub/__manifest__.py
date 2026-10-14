{
    'name': 'DMAG Lead 360°',
    'version': '17.0.1.0.0',
    'category': 'Sales/CRM',
    'summary': 'Nút và tab liên kết từ lead tới phòng khám, đơn kê, báo giá, hợp đồng, hoá đơn, thanh toán, '
               'lộ trình triển khai, dự án, hội thoại, cuộc gọi và hoa hồng; tóm tắt tài chính trên lead',
    'author': 'DMAG',
    'license': 'LGPL-3',
    'depends': ['dmag_omnichannel', 'dmag_contract', 'dmag_delivery', 'dmag_commission'],
    'data': [
        'views/crm_lead_views.xml',
        'views/res_partner_views.xml',
    ],
    'auto_install': False,
    'installable': True,
}
