from datetime import timedelta

from odoo import _, fields, models

DEFAULT_SESSIONS = {'guided': 2, 'one_on_one': 4}


class SaleOrder(models.Model):
    _inherit = 'sale.order'

    dmag_delivery_plan_ids = fields.One2many('dmag.delivery.plan', 'sale_order_id', string='Lộ trình triển khai')
    dmag_delivery_plan_count = fields.Integer(compute='_compute_dmag_delivery_plan_count')

    def _compute_dmag_delivery_plan_count(self):
        for order in self:
            order.dmag_delivery_plan_count = len(order.dmag_delivery_plan_ids)

    def action_confirm(self):
        result = super().action_confirm()
        self._dmag_create_delivery_plans()
        return result

    def _dmag_create_delivery_plans(self):
        Plan = self.env['dmag.delivery.plan']
        for order in self:
            module_lines = order.order_line.filtered(
                lambda line: line.product_id.product_tmpl_id.dmag_is_module and line.dmag_tier)
            if not module_lines or order.dmag_delivery_plan_ids:
                continue
            clinic = order.partner_id.commercial_partner_id
            responsible = clinic.dmag_account_owner_id or order.user_id or self.env.user
            start = fields.Date.today()
            plan = Plan.create({
                'partner_id': clinic.id,
                'sale_order_id': order.id,
                'user_id': responsible.id,
                'date_start': start,
            })
            for sequence, sale_line in enumerate(module_lines, start=1):
                plan._dmag_add_line(sale_line, sequence, start, responsible)
            if clinic.dmag_lifecycle not in ('active',):
                clinic.dmag_lifecycle = 'active'
            plan.message_post(body=_('Lộ trình được tạo tự động từ đơn bán %s.', order.name))


class DmagDeliveryPlan(models.Model):
    _inherit = 'dmag.delivery.plan'

    def _dmag_add_line(self, sale_line, sequence, start, responsible):
        self.ensure_one()
        template = sale_line.product_id.product_tmpl_id
        tier = template.dmag_tier
        deadline = start + timedelta(days=template.dmag_duration_days or 90)
        vals = {
            'plan_id': self.id,
            'sequence': sequence,
            'product_id': sale_line.product_id.id,
            'sale_line_id': sale_line.id,
            'tier': tier,
            'pillar_id': template.dmag_pillar_id.id,
            'user_id': responsible.id,
            'date_start': start,
            'date_deadline': deadline,
        }
        if tier in ('self', 'guided') and template.dmag_channel_id:
            channel = template.dmag_channel_id.sudo()
            clinic = self.partner_id.commercial_partner_id
            channel._action_add_members(clinic.child_ids or clinic)
            vals['channel_id'] = channel.id
        if tier in ('guided', 'one_on_one'):
            vals['sessions_total'] = template.dmag_session_count or DEFAULT_SESSIONS[tier]
        if tier == 'field':
            vals['project_id'] = self._dmag_create_field_project(template, start, deadline, responsible).id
        return self.env['dmag.delivery.line'].create(vals)

    def _dmag_create_field_project(self, template, start, deadline, responsible):
        """Dự án thực địa theo mẫu: kickoff + N Sprint + nghiệm thu, áp dụng nguyên tắc Zero-Zalo."""
        clinic = self.partner_id.commercial_partner_id
        sprints = template.dmag_sprint_count or 3
        span = max(1, (deadline - start).days // sprints)
        project = self.env['project.project'].create({
            'name': f'[Thực địa] {template.name} – {clinic.name}',
            'partner_id': clinic.id,
            'user_id': responsible.id,
            'date_start': start,
            'date': deadline,
            'description': _('Mọi việc giao – check-in – nghiệm thu chỉ hợp lệ khi nằm trên dự án này (Zero-Zalo). '
                             'Mỗi task cần đủ: người phụ trách, KR liên kết, đầu ra, hạn chót.'),
        })
        tasks = [{
            'name': _('Kickoff & thống nhất KR 90 ngày'),
            'project_id': project.id,
            'user_ids': [fields.Command.set(responsible.ids)],
            'date_deadline': fields.Datetime.to_datetime(start + timedelta(days=3)),
        }]
        for index in range(1, sprints + 1):
            tasks.append({
                'name': _('Sprint %(n)s – triển khai & nghiệm thu', n=index),
                'project_id': project.id,
                'user_ids': [fields.Command.set(responsible.ids)],
                'date_deadline': fields.Datetime.to_datetime(start + timedelta(days=span * index)),
            })
        self.env['project.task'].create(tasks)
        return project
