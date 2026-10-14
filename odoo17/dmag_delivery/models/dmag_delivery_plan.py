from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.dmag_crm.models.dmag_segment import TIER_SELECTION
from odoo.addons.project.models.project_task import CLOSED_STATES

PULSE_SELECTION = [
    ('green', 'Xanh'),
    ('yellow', 'Vàng'),
    ('red', 'Đỏ'),
]
UNPAID_STATES = ('not_paid', 'partial')

# Ngưỡng cờ Pulse (ngày). Bản demo, chỉnh khi DMAG chốt quy chế.
LATE_RED_DAYS = 7
OVERDUE_RED_DAYS = 7
SILENCE_YELLOW_DAYS = 7
SILENCE_RED_DAYS = 21
REAUDIT_NOTICE_DAYS = 7


class DmagDeliveryPlan(models.Model):
    _name = 'dmag.delivery.plan'
    _description = 'Lộ trình triển khai'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'pulse_rank desc, date_start desc, id desc'

    name = fields.Char('Mã lộ trình', required=True, copy=False, readonly=True, default=lambda self: _('Mới'))
    partner_id = fields.Many2one('res.partner', string='Phòng khám', required=True, index=True, tracking=True)
    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', index=True, readonly=True)
    prescription_id = fields.Many2one(related='sale_order_id.dmag_prescription_id', string='Đơn kê')
    user_id = fields.Many2one('res.users', string='Phụ trách', tracking=True, domain=[('share', '=', False)])
    date_start = fields.Date('Ngày bắt đầu', default=fields.Date.today, required=True)
    date_day90 = fields.Date('Mốc ngày 90', compute='_compute_date_day90', store=True)
    state = fields.Selection([
        ('active', 'Đang triển khai'),
        ('paused', 'Tạm dừng'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Huỷ'),
    ], default='active', required=True, tracking=True)
    line_ids = fields.One2many('dmag.delivery.line', 'plan_id', string='Hạng mục')
    session_ids = fields.One2many('dmag.delivery.session', 'plan_id', string='Buổi làm việc')
    progress = fields.Float('Tiến độ (%)', compute='_compute_progress')
    pulse = fields.Selection(PULSE_SELECTION, string='Pulse', default='green', tracking=True)
    pulse_rank = fields.Integer(compute='_compute_pulse_rank', store=True)
    pulse_reason = fields.Text('Lý do Pulse')
    pulse_date = fields.Date('Cập nhật Pulse')
    reaudit_id = fields.Many2one('dmag.dda.audit', string='DDA lần 2', readonly=True)
    reaudit_reminded = fields.Boolean(copy=False)
    project_count = fields.Integer(compute='_compute_counts')
    session_count = fields.Integer(compute='_compute_counts')
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Mới')) == _('Mới'):
                vals['name'] = self.env['ir.sequence'].next_by_code('dmag.delivery.plan') or _('Mới')
        return super().create(vals_list)

    @api.depends('date_start')
    def _compute_date_day90(self):
        for plan in self:
            plan.date_day90 = plan.date_start and plan.date_start + timedelta(days=90)

    @api.depends('pulse')
    def _compute_pulse_rank(self):
        ranks = {'green': 0, 'yellow': 1, 'red': 2}
        for plan in self:
            plan.pulse_rank = ranks.get(plan.pulse, 0)

    def _compute_progress(self):
        for plan in self:
            plan.progress = (sum(plan.line_ids.mapped('progress')) / len(plan.line_ids)) if plan.line_ids else 0.0

    def _compute_counts(self):
        for plan in self:
            plan.project_count = len(plan.line_ids.project_id)
            plan.session_count = len(plan.session_ids)

    # ------------------------------------------------------------------
    # Pulse: quản trị theo ngoại lệ
    # ------------------------------------------------------------------
    def _last_activity_date(self):
        self.ensure_one()
        dates = [self.date_start]
        dates += [d for d in self.line_ids.mapped('last_activity_date') if d]
        return max(dates)

    def _evaluate_pulse(self, today=None):
        """Trả về (pulse, [lý do]) cho một lộ trình."""
        self.ensure_one()
        today = today or fields.Date.today()
        red, yellow = [], []
        for line in self.line_ids.filtered(lambda l: l.date_deadline and l.progress < 100):
            late = (today - line.date_deadline).days
            if late > LATE_RED_DAYS:
                red.append(_('%(item)s trễ %(days)s ngày', item=line.display_name, days=late))
            elif late > 0:
                yellow.append(_('%(item)s trễ %(days)s ngày', item=line.display_name, days=late))
        invoices = self.sale_order_id.invoice_ids.filtered(
            lambda inv: inv.state == 'posted' and inv.payment_state in UNPAID_STATES and inv.invoice_date_due)
        for invoice in invoices:
            overdue = (today - invoice.invoice_date_due).days
            if overdue > OVERDUE_RED_DAYS:
                red.append(_('Hoá đơn %(inv)s quá hạn %(days)s ngày', inv=invoice.name, days=overdue))
            elif overdue > 0:
                yellow.append(_('Hoá đơn %(inv)s quá hạn %(days)s ngày', inv=invoice.name, days=overdue))
        silence = (today - self._last_activity_date()).days
        if silence > SILENCE_RED_DAYS:
            red.append(_('Không có hoạt động/check-in %s ngày', silence))
        elif silence > SILENCE_YELLOW_DAYS:
            yellow.append(_('Không có hoạt động/check-in %s ngày', silence))
        total_days = (self.date_day90 - self.date_start).days or 90
        elapsed = max(0, (today - self.date_start).days)
        expected = min(100.0, 100.0 * elapsed / total_days)
        if expected >= 30 and self.progress < expected * 0.5:
            yellow.append(_('Tiến độ %(actual).0f%% so với kế hoạch %(expected).0f%%',
                            actual=self.progress, expected=expected))
        if red:
            return 'red', red + yellow
        if yellow:
            return 'yellow', yellow
        return 'green', []

    def _update_pulse(self, today=None):
        today = today or fields.Date.today()
        for plan in self.filtered(lambda p: p.state == 'active'):
            pulse, reasons = plan._evaluate_pulse(today)
            changed = pulse != plan.pulse
            plan.write({'pulse': pulse, 'pulse_reason': '\n'.join(reasons), 'pulse_date': today})
            if changed and pulse in ('yellow', 'red'):
                plan.activity_schedule(
                    'mail.mail_activity_data_todo',
                    date_deadline=today,
                    summary=_('Pulse %s – cần can thiệp', dict(PULSE_SELECTION)[pulse]),
                    note='<br/>'.join(reasons),
                    user_id=(plan.user_id or self.env.user).id,
                )

    def _remind_reaudit(self, today=None):
        today = today or fields.Date.today()
        due = self.filtered(lambda p: p.state == 'active' and not p.reaudit_id and not p.reaudit_reminded
                            and p.date_day90 and (p.date_day90 - today).days <= REAUDIT_NOTICE_DAYS)
        for plan in due:
            plan.activity_schedule(
                'mail.mail_activity_data_todo',
                date_deadline=plan.date_day90,
                summary=_('Hẹn DDA lần 2 (mốc ngày 90)'),
                user_id=(plan.user_id or self.env.user).id,
            )
            plan.reaudit_reminded = True

    @api.model
    def _cron_daily(self):
        plans = self.search([('state', '=', 'active')])
        plans._update_pulse()
        plans._remind_reaudit()

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------
    def action_refresh_pulse(self):
        self._update_pulse()

    def action_create_reaudit(self):
        self.ensure_one()
        if self.reaudit_id:
            raise UserError(_('Lộ trình đã có hồ sơ DDA lần 2.'))
        self.reaudit_id = self.env['dmag.dda.audit'].create({
            'partner_id': self.partner_id.commercial_partner_id.id,
            'is_reaudit': True,
            'state': 'deposit',
            'date_onsite': self.date_day90,
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dmag.dda.audit',
            'res_id': self.reaudit_id.id,
            'view_mode': 'form',
        }

    def action_done(self):
        self.write({'state': 'done'})

    def action_pause(self):
        self.write({'state': 'paused'})

    def action_resume(self):
        self.write({'state': 'active'})

    def action_view_projects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Dự án thực địa'),
            'res_model': 'project.project',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', self.line_ids.project_id.ids)],
        }

    def action_view_sessions(self):
        self.ensure_one()
        action = self.env['ir.actions.act_window']._for_xml_id('dmag_delivery.action_dmag_delivery_session')
        action['domain'] = [('plan_id', '=', self.id)]
        action['context'] = {'default_plan_id': self.id}
        return action


class DmagDeliveryLine(models.Model):
    _name = 'dmag.delivery.line'
    _description = 'Hạng mục lộ trình triển khai'
    _order = 'plan_id, sequence, id'

    plan_id = fields.Many2one('dmag.delivery.plan', required=True, ondelete='cascade', index=True)
    partner_id = fields.Many2one(related='plan_id.partner_id', store=True)
    sequence = fields.Integer(default=10)
    product_id = fields.Many2one('product.product', string='Module', required=True)
    sale_line_id = fields.Many2one('sale.order.line', string='Dòng đơn bán')
    tier = fields.Selection(TIER_SELECTION, string='Hình thức', required=True)
    pillar_id = fields.Many2one('dmag.pillar', string='Trụ cột')
    user_id = fields.Many2one('res.users', string='Chuyên gia phụ trách', domain=[('share', '=', False)])
    date_start = fields.Date('Bắt đầu')
    date_deadline = fields.Date('Hạn hoàn thành')
    channel_id = fields.Many2one('slide.channel', string='Khoá eLearning')
    project_id = fields.Many2one('project.project', string='Dự án thực địa')
    sessions_total = fields.Integer('Số buổi')
    session_ids = fields.One2many('dmag.delivery.session', 'line_id', string='Buổi')
    sessions_done = fields.Integer('Buổi đã làm', compute='_compute_progress')
    learning_completion = fields.Float('Hoàn thành khoá (%)', compute='_compute_progress')
    progress = fields.Float('Tiến độ (%)', compute='_compute_progress')
    last_activity_date = fields.Date('Hoạt động gần nhất', compute='_compute_progress')
    status = fields.Selection([
        ('todo', 'Chưa bắt đầu'),
        ('in_progress', 'Đang làm'),
        ('late', 'Trễ hạn'),
        ('done', 'Hoàn thành'),
    ], compute='_compute_progress', string='Trạng thái')

    @api.depends('product_id', 'tier')
    def _compute_display_name(self):
        labels = dict(TIER_SELECTION)
        for line in self:
            line.display_name = f'{line.product_id.name or ""} ({labels.get(line.tier, "")})'

    def _learning_members(self):
        self.ensure_one()
        clinic = self.plan_id.partner_id.commercial_partner_id
        return clinic | clinic.child_ids

    def _compute_progress(self):
        today = fields.Date.today()
        for line in self:
            done_sessions = line.session_ids.filtered(lambda s: s.state == 'done')
            line.sessions_done = len(done_sessions)
            dates = [fields.Date.to_date(s.date) for s in done_sessions if s.date]
            line.learning_completion = 0.0
            if line.channel_id:
                memberships = self.env['slide.channel.partner'].sudo().search([
                    ('channel_id', '=', line.channel_id.id),
                    ('partner_id', 'in', line._learning_members().ids),
                ])
                line.learning_completion = max(memberships.mapped('completion') or [0])
                dates += [fields.Date.to_date(m.write_date) for m in memberships if m.completion]
            session_ratio = 100.0 * line.sessions_done / line.sessions_total if line.sessions_total else 0.0
            if line.tier == 'self':
                progress = line.learning_completion
            elif line.tier == 'guided':
                parts = [line.learning_completion] if line.channel_id else []
                if line.sessions_total:
                    parts.append(session_ratio)
                progress = sum(parts) / len(parts) if parts else 0.0
            elif line.tier == 'one_on_one':
                progress = session_ratio
            else:
                tasks = line.project_id.task_ids
                closed = tasks.filtered(lambda t: t.state in CLOSED_STATES)
                progress = 100.0 * len(closed) / len(tasks) if tasks else 0.0
                dates += [fields.Date.to_date(t.write_date) for t in tasks if t.state in CLOSED_STATES]
            line.progress = min(100.0, progress)
            line.last_activity_date = max(dates) if dates else False
            if line.progress >= 100:
                line.status = 'done'
            elif line.date_deadline and line.date_deadline < today:
                line.status = 'late'
            elif line.progress > 0 or line.sessions_done:
                line.status = 'in_progress'
            else:
                line.status = 'todo'

    def action_add_session(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'dmag.delivery.session',
            'view_mode': 'form',
            'context': {'default_line_id': self.id, 'default_user_id': (self.user_id or self.env.user).id,
                        'default_kind': 'group' if self.tier == 'guided' else 'one_on_one'},
            'target': 'new',
        }
