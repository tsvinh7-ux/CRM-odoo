from odoo import fields, models


class DmagChannelIdentity(models.Model):
    """Một người dùng trên kênh (PSID Facebook, user_id Zalo) gắn với một liên hệ Odoo."""
    _name = 'dmag.channel.identity'
    _description = 'Danh tính khách trên kênh'
    _rec_name = 'name'

    account_id = fields.Many2one('dmag.channel.account', required=True, ondelete='cascade', index=True)
    channel = fields.Selection(related='account_id.channel', store=True)
    external_id = fields.Char('ID trên kênh', required=True, index=True)
    name = fields.Char('Tên hiển thị')
    avatar_url = fields.Char('Ảnh đại diện')
    partner_id = fields.Many2one('res.partner', string='Liên hệ', index=True, ondelete='set null')
    followed = fields.Boolean('Đang quan tâm OA/Page', default=True)
    last_inbound_date = fields.Datetime('Tin gần nhất của khách')

    _external_uniq = models.Constraint('unique(account_id, external_id)', 'Danh tính trên kênh phải là duy nhất.')
