from odoo import models, fields, api
import logging
import json

_logger = logging.getLogger(__name__)
class insurance_disease_code(models.Model):
    _name = 'insurance.odoo.disease.code'
    
    ipdCode = fields.Char(string="IPD Code", help="This field is used to code of the disease as in IPD", required=True)
    disease = fields.Char(string="Disease", help="This field is used to store disease", required=True)
    # insurance_price = fields.Float(string="Insurance Product Price", help="This field is used to store Insurance product price in Insurance System", required=True)
    # odoo_product_id = fields.Many2one('product.product', string="Odoo Product")
    # valid_from = fields.Datetime(string="Valid From")
    # valid_till = fields.Datetime(string="Valid Till")
    is_active = fields.Boolean(string="Is active")    