"""

Handlers for the Roles service.

This is a set of mongodb backed handlers for a REST based authorization
service. The authorization service simply serves up JSON docs that specify
a set of permissions, and the users who have that set of permissions. Here
is a sample JSON object:

{
    "role_owner": "sychan",
    "role_id": "kbase_users",
    "description": "List of user ids who are considered KBase users",
    "members": [
        "sychan",
        "kbasetest",
        "kbauthorz"
    ],
    "role_updater": [
        "sychan",
        "kbauthorz"
    ],
    "read": [],
    "create": [],
    "modify": [],
    "impersonate": [],
    "delete": []
}

   Here are the semantics of the fields:

   'role_id' : 'Unique human readable identifer for role (required)',
   'description' : 'Description of the role (required)',
   'role_owner' : 'Owner(creator) of this role',
   'role_updater' : 'User_ids that can update this role',
   'members' : 'A list of the user_ids who are members of this group',
   'read' : 'List of kbase object ids (strings) that this role allows read privs',
   'modify' : 'List of kbase object ids (strings) that this role allows modify privs',
   'delete' : 'List of kbase object ids (strings) that this role allows delete privs',
   'impersonate' : 'List of kbase user_ids (strings) that this role allows impersonate privs',
   'grant' : 'List of kbase authz role_ids (strings) that this role allows grant privs',
   'create' : 'Boolean value - does this role provide the create privilege'

   The service is typically mounted under /Roles. Here are the authentication requirements
for each HTTP method:

   GET : requires valid token and membership in role_id in settings.kbase_users
   PUT : requires valid token and user in role_owner, or in the role_updater field for object
   POST : requires valid token and membership in role_id in settings.kbase_users
   DELETE : requires valid token and request must come from role_owner of target object

   The GET method supports the MongoDB options for filter and fields. For queries and filter
parameters the filter parameter is passed as the first parameter and the fields parameter is
the second parameter passed into the pymongo collection.find() method, see:

http://api.mongodb.org/python/current/api/pymongo/collection.html

   As an example, the following query returns all role objects that have sychan as a member:
http://authorization_host/Roles?filter={ "members" : "sychan"}

   To pull up only the role_id fields:

http://authorization_host/Roles?filter={ "members" : "sychan"}&fields={"role_id" : "1"}

   To pull up the role_id fields for roles with "test" as part of their name (PCRE regex):

http://authorization_host/Roles?filter={ "role_id" : { "$regex" : ".*test.*" }}&fields={ "role_id" : "1" }


"""


from piston.handler import BaseHandler
from piston.utils import rc
import pprint
import datetime
import json
from pymongo import Connection
from piston.resource import Resource
from django.conf import settings


pp = pprint.PrettyPrinter(indent=4)

# Convert QuerySet into a dictionary keyed on the field named in 2nd parameter
def dictify(objs,key):
    results = {}
    for x in range(len(objs)):
        results[objs[x][key]] = objs[x]
        
    return results

class RoleHandler( BaseHandler):
    allowed_methods = ('GET','POST','PUT','DELETE')
    fields = ('role_id','description','members','read','modify','delete',
              'impersonate','grant','create','role_owner','role_updater')
    exclude = ( '_id', )
    # We need to define the appropriate settings and set them here
    try:
        conn = Connection(settings.MONGODB_CONN)
    except AttributeError as e:
        print "No connection settings specified: %s\n" % e
        conn = Connection(['mongodb.kbase.us'])
    except Exception as e:
        print "Generic exception %s: %s\n" % (type(e),e)
        conn = Connection()
    db = conn.authorization
    roles = db.roles
    # Set the role_id to require for updates to the roles db
    try:
        kbase_users = settings.kbase_users
    except AttributeError as e:
        kbase_users = 'kbase_users'
    # Help object when queries go to the top level with no search specification
    help_json = { 'id' : 'KBase Authorization',
                  'documentation' : 'https://docs.google.com/document/d/1CTkthDUPwNzMF22maLyNIktI1sHdWPwtd3lJk0aFb20/edit',
                  'resources' : { 'role_id' : 'Unique human readable identifer for role (required)',
                                  'description' : 'Description of the role (required)',
                                  'role_owner' : 'Owner(creator) of this role',
                                  'role_updater' : 'User_ids that can update this role',
                                  'members' : 'A list of the user_ids who are members of this group',
                                  'read' : 'List of kbase object ids (strings) that this role allows read privs',
                                  'modify' : 'List of kbase object ids (strings) that this role allows modify privs',
                                  'delete' : 'List of kbase object ids (strings) that this role allows delete privs',
                                  'impersonate' : 'List of kbase user_ids (strings) that this role allows impersonate privs',
                                  'grant' : 'List of kbase authz role_ids (strings) that this role allows grant privs',
                                  'create' : 'Boolean value - does this role provide the create privilege'
                                  },
                  'contact' : { 'email' : 'sychan@lbl.gov'},
                  'usage'   : 'This is a standard REST service. Note that read handler takes\n' + 
                  'MongoDB filtering and JSON field selection options passed as\n' +
                  'URL parameters \'filter\' and \'fields\' respectively.\n' +
                  'Please look at MongoDB pymongo collection documentation for details.\n' +
                  'Read and Create are currently open to all authenticated users in role "%s", but\n' % kbase_users +
                  'delete requires ownership of the document (in field role_owner),\n' + 
                  'update requires ownership or membership in the target document\'s role_updaters list\n'
                  }


    # Check mongodb to see if the user is in kbase_user role, necessary
    # before they can perform any kinds of updates
    # Note that possessing a Globus Online ID is not sufficient
    def check_kbase_user(self, user_id):
        try:
            res = self.roles.find_one( { 'role_id' : self.kbase_users,
                                          'members' : user_id })
            return res is not None
        except:
            return False

    # Get all role_ids associated with a user_id, returns a
    # an array of role_ids (strings)
    def get_user_roles(self, user_id):
        try:
            roles= self.roles.find( { 'members' : user_id },
                                    { 'role_id' : '1' })
            return [ roles[x]['role_id'] for x in range( roles.count())]
        except Exception as e:
            print "Error while fetching roles for user %s: %s" % ( user_id, e)
            return []

    def read(self, request, role_id=None):
        try:
            if not request.user.username or not self.check_kbase_user( request.user.username):
                res = rc.FORBIDDEN
                res.write(' request not from a member of %s' % self.kbase_users)
            else:
                if role_id == None and 'role_id' in request.GET:
                    role_id = request.GET.get('role_id')
                filter = request.GET.get('filter', None)
                fields = request.GET.get('fields', None)
                if role_id == None and filter == None:
                    res = self.help_json
                elif role_id != None:
                    res = self.roles.find_one( { 'role_id': role_id })
                    if res != None:
                        for excl in self.exclude:
                            if excl in res:
                                del res[excl]
                else:
                    filter = json.loads(filter)
                    if fields:
                        fields = json.loads(fields)
                        match = self.roles.find(filter, fields)
                    else:
                        match = self.roles.find( filter )
                    res = [ match[x] for x in range( match.count())]
                    for x in res:
                        for excl in self.exclude:
                            if excl in x:
                                del x[excl]
        except Exception as e:
            res = rc.BAD_REQUEST
            res.write(' error: %s' % e )
        return(res)

    def create(self, request):
        r = request.data
        try:
            if not request.user.username:
                res = rc.FORBIDDEN
                res.write(' request does not have username ')
            elif not self.check_kbase_user( request.user.username):
                res = rc.FORBIDDEN
                res.write(' request not from a member of %s' % self.kbase_users)
            elif self.roles.find( { 'role_id': r['role_id'] }).count() == 0:
                new = { x : r.getlist(x) for x in ('read','modify','delete',
                                                   'impersonate','grant','create','members','role_updater') }
                new['role_id'] = r['role_id']
                new['description'] = r['description']
                new['role_owner'] = request.user.username
                self.roles.insert( new)
                res = rc.CREATED
            else:
                res = rc.DUPLICATE_ENTRY
        except KeyError as e:
            res = rc.BAD_REQUEST
            res.write(' required fields: %s' % e )
        except Exception as e:
            res = rc.BAD_REQUEST
            res.write(' error: %s' % e )
        return(res)
    def update(self, request, role_id=None):
        r = request.data
        try:
            if not request.user.username:
                res = rc.FORBIDDEN
                res.write(' request does not have username ')
            elif not self.check_kbase_user( request.user.username):
                res = rc.FORBIDDEN
                res.write(' request not from a member of %s' % self.kbase_users)
            elif role_id == None:
                role_id = request.data['role_id']
            old = self.roles.find_one( { 'role_id': role_id })
            if old != None:
                if request.user.username == old['role_owner'] or request.user.username in old['role_updater'] :
                    old.update(r)
                    self.roles.save( old)
                    res = rc.CREATED
                else:
                    res = rc.FORBIDDEN
                    res.write( " %s is owned by %s and updated by %s, but request is from user %s" %
                               (old['role_id'],old['role_owner'], pp.pformat(old['role_updater']), request.user.username))
            else:
                res = rc.NOT_HERE
        except KeyError as e:
            res = rc.BAD_REQUEST
            res.write(' required fields: %s' % e )
        except Exception as e:
            res = rc.BAD_REQUEST
            res.write(' error: %s' % e )
        return(res)
    def delete(self, request, role_id = None):
        try:
            if not request.user.username:
                res = rc.FORBIDDEN
                res.write(' request does not have username ')
            elif not self.check_kbase_user( request.user.username):
                res = rc.FORBIDDEN
                res.write(' request not from a member of %s' % self.kbase_users)
            elif role_id is None:
                raise KeyError('No role_id specified')
            old = self.roles.find_one( { 'role_id': role_id })
            if old != None:
                if request.user.username == old['role_owner']:
                    self.roles.remove( { '_id' : old['_id'] }, safe=True)
                    res = rc.DELETED
                else:
                    res = rc.FORBIDDEN
                    res.write( " %s is owned by %s, but request is from user %s" %
                               (old['role_id'],old['role_owner'], request.user.username))
            else:
                res = rc.NOT_HERE
        except KeyError as e:
            res = rc.BAD_REQUEST
            res.write(' role_id must be specified')
        except Exception as e:
            res = rc.BAD_REQUEST
            res.write(' error: %s' % e)
        return(res)



# Handlers for piston API
# sychan 9/6/2012

role_handler = Resource( RoleHandler)
