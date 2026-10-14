from odoo import fields, models


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    dmag_channel_id = fields.Many2one('slide.channel', string='Khoá eLearning',
                                      help='Dùng cho hình thức Tự học / Học có hướng dẫn: khách được ghi danh tự động.')
    dmag_session_count = fields.Integer('Số buổi (1:1 / nhóm)',
                                        help='Kèm 1:1: số buổi riêng. Học có hướng dẫn: số buổi nhóm.')
    dmag_sprint_count = fields.Integer('Số Sprint thực địa', default=3)
    dmag_duration_days = fields.Integer('Thời lượng (ngày)', default=90)
