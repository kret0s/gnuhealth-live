from trytond.model import ModelView, ModelSQL, fields, ModelSingleton
from trytond.pool import Pool
from trytond.wizard import Wizard, StateView, Button, StateTransition, \
    StateAction
from trytond.transaction import Transaction
#
__all__ = ['Student','Configuration']

class Configuration(ModelSingleton, ModelSQL, ModelView):
    'Student Configuration'
    __name__ = 'student.configuration'
    
    
    student_sequence = fields.Property(fields.Many2One('ir.sequence','Student Code Sequence',
                                       domain=[('code', '=', 'student.student')]))

class Student(ModelView, ModelSQL):
    'Student'
    __name__ = 'student.student'
    
    name = fields.Char('Name')
    code = fields.Char('Code')
    age = fields.Integer('Age')
    percentage = fields.Numeric('Percentage', digits=(3, 2))
    school_id = fields.Many2One(
        'school.school', 'School', required=True,
        help='Select School for Student')
    comment = fields.Text('Comment',help='Enter additional Information')
    origin = fields.Reference('Origin', selection='get_origin', select=True)

    @classmethod
    def _get_origin(cls):
        'Return list of Model names for origin Reference'
        return ['sale.sale']

    @classmethod
    def get_origin(cls):
        Model = Pool().get('ir.model')
        models = cls._get_origin()
        models = Model.search([
                ('model', 'in', models),
                ])
        return [(None, '')] + [(m.model, m.name) for m in models]
    
#    @classmethod
#    def create(cls, vlist):
#        Sequence = Pool().get('ir.sequence')
#        Config = Pool().get('student.configuration')
#        vlist = [x.copy() for x in vlist]
#
#        for values in vlist:
#            if not values.get('code'):
#                config = Config(1)
#                print config
#                values['code'] = Sequence.get_id(
#                    config.student_sequence.id)
#        return super(Student, cls).create(vlist)
#    
    
    
#    @classmethod
#    def write(cls, *args):
##        print iter(args)
#        print args
#        actions = iter(args)
#        args = []
##        print actions
#        for student, values in zip(actions,actions):
##            student_record = Pool().get('student.student')
##            print student_record
##            print cls  
#            print cls.browse(student[0])[0].name
#            print values
##            
##            if not values.get('active', True):
##                childs = cls.search([
##                        ('parent', 'child_of', [a.id for a in accounts]),
##                        ])
##                if MoveLine.search([
##                            ('account', 'in', [a.id for a in childs]),
##                            ]):
##                    values = values.copy()
##                    del values['active']
#            args.extend((student, values))
#            print args
#            5/0
#        super(Account, cls).write(*args)