from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

STATE_SELECTION = [
    ('draft', 'Nháp'),
    ('confirmed', 'Nhân sự đã xác nhận'),
    ('approved', 'Quản lý đã duyệt'),
    ('payroll', 'Đã đẩy sang lương'),
]


class DmagCommissionStatement(models.Model):
    _name = 'dmag.commission.statement'
    _description = 'Bảng kê hoa hồng tháng'
    _inherit = ['mail.thread']
    _order = 'date_from desc, user_id'

    name = fields.Char(compute='_compute_name', store=True)
    user_id = fields.Many2one('res.users', string='Nhân sự', required=True, index=True)
    date_from = fields.Date('Từ ngày', required=True)
    date_to = fields.Date('Đến ngày', required=True)
    line_ids = fields.One2many('dmag.commission.line', 'statement_id', string='Dòng hoa hồng')
    assignment_id = fields.Many2one('dmag.commission.assignment', string='Chính sách áp dụng',
                                    compute='_compute_amounts', store=True)
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    target = fields.Monetary('Mục tiêu thực thu', compute='_compute_amounts', store=True)
    collected = fields.Monetary('Thực thu (người chốt)', compute='_compute_amounts', store=True)
    achievement = fields.Float('Hoàn thành (%)', compute='_compute_amounts', store=True)
    commission_base = fields.Monetary('Hoa hồng gốc', compute='_compute_amounts', store=True)
    multiplier = fields.Float('Hệ số', compute='_compute_amounts', store=True, digits=(16, 3))
    commission_total = fields.Monetary('Hoa hồng phải trả', compute='_compute_amounts', store=True, tracking=True)
    payroll_code = fields.Char('Mã hạng mục lương', default=lambda self: self.env.company.dmag_payroll_code)
    payroll_month = fields.Date('Kỳ lương', help='Tháng lương nhận khoản hoa hồng này (mặc định tháng kế tiếp).')
    state = fields.Selection(STATE_SELECTION, default='draft', required=True, tracking=True)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)

    _sql_constraints = [
        ('period_uniq', 'unique(user_id, date_from, company_id)', 'Mỗi nhân sự chỉ có một bảng kê mỗi kỳ.'),
    ]

    @api.depends('user_id', 'date_from')
    def _compute_name(self):
        for statement in self:
            period = statement.date_from.strftime('%m/%Y') if statement.date_from else ''
            statement.name = _('Hoa hồng %(user)s – %(period)s', user=statement.user_id.name or '', period=period)

    @api.depends('line_ids.amount', 'line_ids.base_amount', 'line_ids.role', 'user_id', 'date_to')
    def _compute_amounts(self):
        Assignment = self.env['dmag.commission.assignment']
        for statement in self:
            assignment = Assignment._get_for(statement.user_id, statement.date_to) if statement.date_to else Assignment
            statement.assignment_id = assignment
            closer_lines = statement.line_ids.filtered(lambda l: l.role == 'closer')
            # Mỗi khoản thu chỉ tính một lần vào thực thu dù người chốt giữ nhiều vai.
            seen, collected = set(), 0.0
            for line in closer_lines:
                key = (line.partial_id.id or line.origin_line_id.id or line.id, line.product_id.id, line.is_clawback)
                if key not in seen:
                    seen.add(key)
                    collected += line.base_amount
            statement.collected = collected
            statement.target = assignment.monthly_target
            statement.achievement = 100.0 * collected / assignment.monthly_target if assignment.monthly_target else 0.0
            base = sum(statement.line_ids.mapped('amount'))
            statement.commission_base = base
            if assignment and base > 0:
                total, multiplier = assignment.plan_id._apply_multiplier(base, collected, assignment.monthly_target)
            else:
                total, multiplier = base, 1.0
            statement.commission_total = total
            statement.multiplier = multiplier

    def action_refresh(self):
        Line = self.env['dmag.commission.line']
        for statement in self:
            if statement.state != 'draft':
                raise UserError(_('Chỉ cập nhật bảng kê ở trạng thái Nháp.'))
            Line.search([
                ('user_id', '=', statement.user_id.id),
                ('statement_id', '=', False),
                ('date', '>=', statement.date_from),
                ('date', '<=', statement.date_to),
                ('company_id', '=', statement.company_id.id),
            ]).statement_id = statement

    def action_confirm(self):
        for statement in self:
            if statement.state != 'draft':
                continue
            if self.env.user != statement.user_id and not self.env.user.has_group('dmag_crm.group_dmag_manager'):
                raise UserError(_('Chỉ người hưởng hoặc quản lý được xác nhận bảng kê.'))
            statement.state = 'confirmed'

    def action_approve(self):
        if not self.env.user.has_group('dmag_crm.group_dmag_manager'):
            raise UserError(_('Chỉ quản lý được duyệt bảng kê hoa hồng.'))
        for statement in self.filtered(lambda s: s.state == 'confirmed'):
            statement.write({
                'state': 'approved',
                'payroll_month': statement.payroll_month or statement.date_from + relativedelta(months=1),
            })

    def action_push_payroll(self):
        """Đánh dấu đã chuyển sang lương.

        Odoo Community không có app Lương; khi DMAG chốt module lương (BizApps / OCA payroll),
        điểm nối là hàm _dmag_payroll_input_vals() dưới đây để tạo dòng thu nhập HOA_HONG.
        """
        for statement in self:
            if statement.state != 'approved':
                raise UserError(_('Chỉ đẩy sang lương bảng kê đã được quản lý duyệt.'))
            statement.state = 'payroll'
            statement.message_post(body=_('Đã chuyển %(amount)s vào kỳ lương %(month)s, hạng mục %(code)s.',
                                          amount=statement.currency_id.format(statement.commission_total),
                                          month=statement.payroll_month.strftime('%m/%Y'),
                                          code=statement.payroll_code))

    def _dmag_payroll_input_vals(self):
        self.ensure_one()
        return {
            'code': self.payroll_code,
            'name': self.name,
            'amount': self.commission_total,
            'user_id': self.user_id.id,
            'month': self.payroll_month,
        }

    def action_reset_draft(self):
        if not self.env.user.has_group('dmag_crm.group_dmag_manager'):
            raise UserError(_('Chỉ quản lý được mở lại bảng kê.'))
        self.filtered(lambda s: s.state != 'payroll').write({'state': 'draft'})

    @api.model
    def _generate_for_month(self, day):
        day = fields.Date.to_date(day)
        date_from = day.replace(day=1)
        date_to = date_from + relativedelta(months=1, days=-1)
        lines = self.env['dmag.commission.line'].search([
            ('statement_id', '=', False), ('date', '>=', date_from), ('date', '<=', date_to),
            ('company_id', '=', self.env.company.id),
        ])
        statements = self.browse()
        for user in lines.user_id:
            statement = self.search([('user_id', '=', user.id), ('date_from', '=', date_from),
                                     ('company_id', '=', self.env.company.id)], limit=1)
            if not statement:
                statement = self.create({'user_id': user.id, 'date_from': date_from, 'date_to': date_to})
            if statement.state == 'draft':
                statement.action_refresh()
            statements |= statement
        return statements
