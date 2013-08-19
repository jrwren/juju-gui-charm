# This file is part of the Juju GUI, which lets users view and manage Juju
# environments within a graphical interface (https://launchpad.net/juju-gui).
# Copyright (C) 2013 Canonical Ltd.
#
# This program is free software: you can redistribute it and/or modify it under
# the terms of the GNU Affero General Public License version 3, as published by
# the Free Software Foundation.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranties of MERCHANTABILITY,
# SATISFACTORY QUALITY, or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.

"""Bundle deployment views.

This module includes the views used to create responses for bundle deployments
related requests. The bundles protocol, described in the bundles package
docstring, mimics the request/response paradigm over a WebSocket. Views are
simple functions that, given a request, return a response to be sent back to
the API client. Each view receives the following arguments:

    - request: a request object with two attributes:
      - request.params: a dict representing the parameters sent by the client;
      - request.user: the current user (an instance of guiserver.auth.User);
    - deployer: a Deployer instance, ready to be used to schedule/start bundle
      deployments.

The response returned by views must be an instance of tornado.gen.Return,
containing the response data as a dict-like object, e.g.:

    {'Response': {}, 'Error': 'this field is optional'}

The response function defined in the guiserver.bundles.utils module helps
creating this kind of responses:

    from guiserver.bundles.utils import response

    @gen.coroutine
    def succeeding_view(request, deployer)
        raise response(info='Success!')

    @gen.coroutine
    def failing_view(request, deployer)
        raise response(error='Boo!')

Use the require_authenticated_user decorator if the view requires a logged in
user, e.g.:

    @gen.coroutine
    @require_authenticated_user
    def protected_view(request, deployer):
        # This function body is executed only if the user is authenticated.

As seen in the examples above, views are also coroutines: they must be
decorated with tornado.gen.coroutine, they can suspend their own execution
using "yield", and they must return their results using "raise response(...)"
(the latter will be eventually fixed switching to a newer version of Python).
"""

from tornado import gen
import yaml

from guiserver.bundles.utils import (
    require_authenticated_user,
    response,
)


def _validate_import_params(params):
    """Parse the request data and return a (name, bundle) tuple.

    In the tuple:
      - name is the name of the bundle to be imported;
      - bundle is the YAML decoded bundle object.

    Raise a ValueError if data represents an invalid request.
    """
    name = params.get('Name')
    contents = params.get('YAML')
    if not (name and contents):
        raise ValueError('invalid data parameters')
    try:
        bundles = yaml.load(contents, Loader=yaml.SafeLoader)
    except Exception as err:
        raise ValueError('invalid YAML contents: {}'.format(err))
    bundle = bundles.get(name)
    if bundle is None:
        raise ValueError('bundle not found')
    return name, bundle


@gen.coroutine
@require_authenticated_user
def import_bundle(request, deployer):
    """Start or schedule a bundle deployment.

    If the request is valid, the response will contain the DeploymentId
    assigned to the bundle deployment.
    """
    # Validate the request parameters.
    try:
        name, bundle = _validate_import_params(request.params)
    except ValueError as err:
        raise response(error='invalid request: {}'.format(err))
    # Validate the bundle against the current state of the Juju environment.
    err = yield deployer.validate(request.user, name, bundle)
    if err is not None:
        raise response(error='invalid request: {}'.format(err))
    # Add the bundle deployment to the Deployer queue.
    deployment_id = deployer.import_bundle(request.user, name, bundle)
    raise response(info={'DeploymentId': deployment_id})


@gen.coroutine
@require_authenticated_user
def watch(request, deployer):
    """Handle requests for watching a given deployment.

    The deployment is identified in the request by the DeploymentId parameter.
    If the request is valid, the response will contain the WatcherId
    to be used to observe the deployment progress.
    """
    deployment_id = request.params.get('DeploymentId')
    if deployment_id is None:
        raise response(error='invalid request: invalid data parameters')
    # Retrieve a watcher identifier from the Deployer.
    watcher_id = deployer.watch(deployment_id)
    if watcher_id is None:
        raise response(error='invalid request: deployment not found')
    raise response(info={'WatcherId': watcher_id})


@gen.coroutine
@require_authenticated_user
def next(request, deployer):
    """Wait until a new deployment event is available to be sent to the client.

    The request params must include a WatcherId value, used to identify the
    deployment being observed. If unseen changes are available, a response is
    suddenly returned containing the changes. Otherwise, this views suspends
    its execution until a new change is notified by the Deployer.
    """
    watcher_id = request.params.get('WatcherId')
    if watcher_id is None:
        raise response(error='invalid request: invalid data parameters')
    # Wait for the Deployer to send changes.
    changes = yield deployer.next(watcher_id)
    if changes is None:
        raise response(error='invalid request: invalid watcher identifier')
    raise response(info={'Changes': changes})


@gen.coroutine
@require_authenticated_user
def status(request, deployer):
    """Return the current status of all the bundle deployments."""
    last_changes = deployer.status()
    raise response(info={'LastChanges': last_changes})
