{
    'name': 'DMAG Hoa hồng theo thực thu',
    'version': '17.0.1.0.0',
    'category': 'Sales/Commissions',
    'summary': 'Chính sách hoa hồng theo từng người, chỉ tính trên tiền đã thu và đối soát, '
               'chia người chốt / người chăm lead / Account Owner, trừ lại khi huỷ đối soát, '
               'bảng kê tháng có duyệt, đẩy sang lương hạng mục HOA_HONG',
    'author': 'DMAG',
    'license': 'LGPL-3',
    'depends': ['dmag_dda', 'sale_crm', 'account'],
    'data': [
        'security/dmag_commission_security.xml',
        'security/ir.model.access.csv',
        'views/dmag_commission_plan_views.xml',
        'views/dmag_commission_line_views.xml',
        'views/dmag_commission_statement_views.xml',
        'views/product_views.xml',
        'views/res_company_views.xml',
        'wizard/dmag_commission_generate_views.xml',
        'views/dmag_commission_menus.xml',
    ],
    'demo': [
        'demo/dmag_commission_demo.xml',
    ],
    'installable': True,
}
