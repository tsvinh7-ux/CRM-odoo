from odoo import fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    dmag_stringee_user_id = fields.Char('Stringee user ID',
                                        help='ID người dùng trên Stringee (softphone/app). Dùng để đổ chuông cho nhân viên.')
    dmag_stringee_phone = fields.Char('Số điện thoại nhận cuộc gọi Stringee',
                                      help='Dùng khi nhân viên nghe bằng điện thoại thường thay vì softphone.')

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + ['dmag_stringee_user_id', 'dmag_stringee_phone']
