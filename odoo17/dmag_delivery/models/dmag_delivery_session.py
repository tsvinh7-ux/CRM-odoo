from datetime import timedelta

from odoo import _, api, fields, models


class DmagDeliverySession(models.Model):
    """Buổi kèm 1:1 / buổi nhóm / buổi onsite, kèm biên bản."""
    _name = 'dmag.delivery.session'
    _description = 'Buổi làm việc triển khai'
    _inherit = ['mail.thread']
    _order = 'date desc, id desc'

    line_id = fields.Many2one('dmag.delivery.line', string='Hạng mục', required=True, ondelete='cascade', index=True)
    plan_id = fields.Many2one(related='line_id.plan_id', store=True, index=True)
    partner_id = fields.Many2one(related='line_id.plan_id.partner_id', store=True, string='Phòng khám')
    name = fields.Char('Chủ đề', required=True, default=lambda self: _('Buổi làm việc'))
    kind = fields.Selection([
        ('one_on_one', 'Kèm 1:1'),
        ('group', 'Buổi nhóm'),
        ('onsite', 'Onsite'),
    ], default='one_on_one', required=True, string='Loại')
    date = fields.Datetime('Thời gian', default=fields.Datetime.now, required=True)
    duration = fields.Float('Thời lượng (giờ)', default=1.5)
    user_id = fields.Many2one('res.users', string='Chuyên gia', default=lambda self: self.env.user)
    state = fields.Selection([
        ('planned', 'Đã hẹn'),
        ('done', 'Đã diễn ra'),
        ('cancel', 'Huỷ'),
    ], default='planned', required=True, tracking=True)
    situation = fields.Html('Hiện trạng')
    work_done = fields.Html('Việc đã làm')
    commitments = fields.Html('Cam kết của phòng khám')
    next_deadline = fields.Date('Hạn cam kết')
    calendar_event_id = fields.Many2one('calendar.event', string='Lịch', readonly=True, copy=False)

    def action_schedule(self):
        for session in self.filtered(lambda s: not s.calendar_event_id):
            clinic = session.partner_id.commercial_partner_id
            attendees = (clinic.child_ids or clinic) | session.user_id.partner_id
            session.calendar_event_id = self.env['calendar.event'].create({
                'name': f'[DMAG] {session.name} – {clinic.name}',
                'start': session.date,
                'stop': session.date + timedelta(hours=session.duration or 1),
                'user_id': session.user_id.id,
                'partner_ids': [fields.Command.set(attendees.ids)],
            })

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})
        self.calendar_event_id.unlink()

    @api.model_create_multi
    def create(self, vals_list):
        sessions = super().create(vals_list)
        sessions.filtered(lambda s: s.state == 'planned').action_schedule()
        return sessions
