from trytond.model import ModelView, ModelSQL, fields

from trytond.report import Report
from trytond.wizard import Wizard, StateAction, StateView, Button
from trytond.pyson import Eval, Not, Bool, PYSONEncoder, Equal, And, Or, If

from trytond.modules.company import CompanyReport

__all__ = ['School',
           'SchoolReport',
           ]


class School(ModelView, ModelSQL):
    'School'
    __name__ = 'school.school'
    
    name = fields.Char('New Name')
    code = fields.Char('School Code')
    photo = fields.Binary('Picture')
    
    student_ids = fields.One2Many('student.student', 'school_id','Students')
    state = fields.Selection([
        ('draft', 'Registration Pending'),
        ('approved', 'Registered'),
        ], 'State', sort=False)
    
    
    @classmethod
    def __setup__(cls):
        super(School, cls).__setup__()

        cls._buttons.update({
            'approve_school': {'invisible': Equal(Eval('state'), 'approved')}
            })
        
    @staticmethod
    def default_state():
        return 'draft'
    
    @classmethod
    @ModelView.button
    def approve_school(cls, schools):
        school = schools[0]
#        "Chnage School state to Approved"
        cls.write(schools, {
            'state': 'approved',})
        
class SchoolReport(CompanyReport):
    __name__ = 'school.school'
