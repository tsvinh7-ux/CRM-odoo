from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .product_template import COMMISSION_GROUP_SELECTION


class DmagCommissionPlan(models.Model):
    _name = 'dmag.commission.plan'
    _description = 'Chính sách hoa hồng'
    _inherit = ['mail.thread']

    name = fields.Char('Tên chính sách', required=True, tracking=True)
    active = fields.Boolean(default=True)
    line_ids = fields.One2many('dmag.commission.plan.line', 'plan_id', string='Tỷ lệ theo nhóm', copy=True)
    low_threshold = fields.Float('Ngưỡng thấp (% mục tiêu)', default=70.0, tracking=True)
    low_multiplier = fields.Float('Hệ số dưới ngưỡng thấp', default=0.8, tracking=True)
    high_threshold = fields.Float('Ngưỡng vượt (% mục tiêu)', default=100.0, tracking=True)
    high_multiplier = fields.Float('Hệ số cho phần vượt', default=1.2, tracking=True)
    note = fields.Html('Ghi chú')

    def _rate_for(self, group):
        self.ensure_one()
        line = self.line_ids.filtered(lambda l: l.commission_group == group)[:1]
        return line.rate if line else 0.0

    def _apply_multiplier(self, commission, collected, target):
        """Hệ số theo mức hoàn thành mục tiêu thực thu tháng.

        < ngưỡng thấp: × hệ số thấp toàn bộ. Từ ngưỡng thấp đến 100%: × 1.
        > 100%: phần hoa hồng tương ứng với phần thu vượt mục tiêu được × hệ số vượt.
        """
        self.ensure_one()
        if not target or not collected:
            return commission, 1.0
        achievement = 100.0 * collected / target
        if achievement < self.low_threshold:
            return commission * self.low_multiplier, self.low_multiplier
        if achievement <= self.high_threshold:
            return commission, 1.0
        excess_share = (collected - target) / collected
        total = commission + commission * excess_share * (self.high_multiplier - 1.0)
        return total, total / commission if commission else 1.0


class DmagCommissionPlanLine(models.Model):
    _name = 'dmag.commission.plan.line'
    _description = 'Tỷ lệ hoa hồng theo nhóm sản phẩm'

    plan_id = fields.Many2one('dmag.commission.plan', required=True, ondelete='cascade', index=True)
    commission_group = fields.Selection(COMMISSION_GROUP_SELECTION, string='Nhóm sản phẩm', required=True)
    rate = fields.Float('Tỷ lệ (%)', required=True)

    _group_uniq = models.Constraint('unique(plan_id, commission_group)', 'Mỗi nhóm chỉ có một tỷ lệ trong chính sách.')


class DmagCommissionAssignment(models.Model):
    """Gán chính sách cho từng nhân sự, có thể ghi đè tỷ lệ riêng."""
    _name = 'dmag.commission.assignment'
    _description = 'Gán chính sách hoa hồng'
    _inherit = ['mail.thread']
    _order = 'user_id, date_from desc'

    user_id = fields.Many2one('res.users', string='Nhân sự', required=True, index=True, tracking=True,
                              domain=[('share', '=', False)])
    plan_id = fields.Many2one('dmag.commission.plan', string='Chính sách', required=True, tracking=True)
    date_from = fields.Date('Hiệu lực từ', required=True, default=fields.Date.today, tracking=True)
    date_to = fields.Date('Đến', tracking=True)
    monthly_target = fields.Monetary('Mục tiêu thực thu/tháng', tracking=True,
                                     help='Dùng để tính hệ số hoàn thành mục tiêu. Tính trên số tiền đã thu chưa VAT '
                                          'của các khoản mà nhân sự là người chốt.')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    override_ids = fields.One2many('dmag.commission.assignment.override', 'assignment_id', string='Tỷ lệ riêng')
    state = fields.Selection([('draft', 'Nháp'), ('approved', 'Đã duyệt')], default='draft', tracking=True)

    @api.constrains('user_id', 'date_from', 'date_to', 'state')
    def _check_overlap(self):
        for assignment in self.filtered(lambda a: a.state == 'approved'):
            domain = [
                ('id', '!=', assignment.id), ('user_id', '=', assignment.user_id.id), ('state', '=', 'approved'),
                '|', ('date_to', '=', False), ('date_to', '>=', assignment.date_from),
            ]
            if assignment.date_to:
                domain.append(('date_from', '<=', assignment.date_to))
            if self.search_count(domain):
                raise ValidationError(_('%s đã có chính sách hoa hồng hiệu lực trùng thời gian.',
                                        assignment.user_id.name))

    @api.depends('user_id', 'plan_id', 'date_from')
    def _compute_display_name(self):
        for assignment in self:
            assignment.display_name = f'{assignment.user_id.name or ""} · {assignment.plan_id.name or ""}'

    def action_approve(self):
        self.write({'state': 'approved'})

    def action_reset_draft(self):
        self.write({'state': 'draft'})

    @api.model
    def _get_for(self, user, day):
        return self.search([
            ('user_id', '=', user.id), ('state', '=', 'approved'), ('date_from', '<=', day),
            '|', ('date_to', '=', False), ('date_to', '>=', day),
        ], order='date_from desc', limit=1)

    def _rate_for(self, group):
        self.ensure_one()
        override = self.override_ids.filtered(lambda o: o.commission_group == group)[:1]
        return override.rate if override else self.plan_id._rate_for(group)


class DmagCommissionAssignmentOverride(models.Model):
    _name = 'dmag.commission.assignment.override'
    _description = 'Tỷ lệ hoa hồng riêng của nhân sự'

    assignment_id = fields.Many2one('dmag.commission.assignment', required=True, ondelete='cascade', index=True)
    commission_group = fields.Selection(COMMISSION_GROUP_SELECTION, string='Nhóm sản phẩm', required=True)
    rate = fields.Float('Tỷ lệ riêng (%)', required=True)


class DmagCommissionDemo(models.AbstractModel):
    _name = 'dmag.commission.demo'
    _description = 'Tiện ích dữ liệu minh hoạ hoa hồng'

    @api.model
    def _collect(self, order_ids, ratio=1.0):
        """Xác nhận đơn, xuất hoá đơn và ghi nhận thanh toán (dùng cho demo)."""
        for order in self.env['sale.order'].browse(order_ids):
            if order.state not in ('sale',):
                order.action_confirm()
            invoices = order._create_invoices()
            invoices.action_post()
            for invoice in invoices:
                self.env['account.payment.register'].with_context(
                    active_model='account.move', active_ids=invoice.ids,
                ).create({'amount': invoice.amount_total * ratio})._create_payments()
