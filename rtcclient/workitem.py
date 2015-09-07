from rtcclient.base import FieldBase
import logging
import xmltodict
import copy
from rtcclient import exception, OrderedDict
from requests.exceptions import HTTPError
from rtcclient.models import Comment
import six


class Workitem(FieldBase):
    """A wrapped class for managing all related resources of the workitem

    :param url: the workitem url
    :param rtc_obj: a reference to the
        :class:`rtcclient.client.RTCClient` object
    :param workitem_id (default is `None`): the id of the workitem, which
        will be retrieved if not specified
    :param raw_data: the raw data ( OrderedDict ) of the request response
    """

    log = logging.getLogger("workitem.Workitem")

    OSLC_CR_RDF = "application/rdf+xml"

    def __init__(self, url, rtc_obj, workitem_id=None, raw_data=None):
        self.identifier = workitem_id
        FieldBase.__init__(self, url, rtc_obj, raw_data)
        if self.identifier is None:
            self.identifier = self.url.split("/")[-1]

    def __str__(self):
        return str(self.identifier)

    def getComments(self):
        """Get all :class:`rtcclient.models.Comment` objects in this workitem

        :return: a :class:`list` contains all the
            :class:`rtcclient.models.Comment` objects
        :rtype: list
        """

        return self.rtc_obj._get_paged_resources("Comment",
                                                 workitem_id=self.identifier,
                                                 page_size="100")

    def getCommentByID(self, comment_id):
        """Get the :class:`rtcclient.models.Comment` object by its id

        Note: the comment id starts from 0

        :param comment_id: the comment id (integer or equivalent string)
        :return: the :class:`rtcclient.models.Comment` object
        :rtype: rtcclient.models.Comment
        """

        # check the validity of comment id
        try:
            if isinstance(comment_id, bool):
                raise ValueError()
            if isinstance(comment_id, six.string_types):
                comment_id = int(comment_id)
            if not isinstance(comment_id, int):
                raise ValueError()
        except (ValueError, TypeError):
            raise exception.BadValue("Please input valid comment id")

        comment_url = "/".join([self.url,
                                "rtc_cm:comments/%s" % comment_id])
        try:
            return Comment(comment_url,
                           self.rtc_obj)
        except HTTPError:
            self.log.error("Comment %s does not exist", comment_id)
            raise exception.BadValue("Comment %s does not exist" % comment_id)

    def addComment(self, msg=None):
        """Add a comment to this workitem

        :param msg: comment message
        :return: the :class:`rtcclient.models.Comment` object
        :rtype: rtcclient.models.Comment
        """

        origin_comment = '''
<rdf:RDF
    xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"
    xmlns:rtc_ext="http://jazz.net/xmlns/prod/jazz/rtc/ext/1.0/"
    xmlns:rtc_cm="http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/"
    xmlns:oslc_cm="http://open-services.net/ns/cm#"
    xmlns:dcterms="http://purl.org/dc/terms/"
    xmlns:oslc_cmx="http://open-services.net/ns/cm-x#"
    xmlns:oslc="http://open-services.net/ns/core#">
  <rdf:Description rdf:about="{0}">
    <rdf:type rdf:resource="http://open-services.net/ns/core#Comment"/>
    <dcterms:description rdf:parseType="Literal">{1}</dcterms:description>
  </rdf:Description>
</rdf:RDF>
'''

        comments_url = "/".join([self.url,
                                 "rtc_cm:comments"])
        headers = copy.deepcopy(self.rtc_obj.headers)
        resp = self.get(comments_url,
                        verify=False,
                        headers=headers)

        raw_data = xmltodict.parse(resp.content)

        total_cnt = raw_data["oslc_cm:Collection"]["@oslc_cm:totalCount"]
        comment_url = "/".join([comments_url,
                                total_cnt])

        comment_msg = origin_comment.format(comment_url, msg)

        headers["Content-Type"] = self.OSLC_CR_RDF
        headers["Accept"] = self.OSLC_CR_RDF
        headers["OSLC-Core-Version"] = "2.0"
        headers["If-Match"] = resp.headers.get("etag")
        req_url = "/".join([comments_url,
                            "oslc:comment"])

        resp = self.post(req_url,
                         verify=False,
                         headers=headers,
                         data=comment_msg)
        self.log.info("Successfully add comment: [%s] for <Workitem %s>",
                      msg, self)

        raw_data = xmltodict.parse(resp.content)
        return Comment(comment_url,
                       self.rtc_obj,
                       raw_data=raw_data["rdf:RDF"]["rdf:Description"])

    def addSubscriber(self, email):
        """Add a subscriber to this workitem

        If the subscriber has already been added, no more actions will be
        performed.

        :param email: the subscriber's email
        """

        headers, raw_data = self._perform_subscribe()
        existed_flag, raw_data = self._add_subscriber(email, raw_data)
        if existed_flag:
            return

        self._update_subscribe(headers, raw_data)
        self.log.info("Successfully add a subscriber: %s for <Workitem %s>",
                      email, self)

    def addSubscribers(self, emails_list):
        """Add subscribers to this workitem

        If the subscribers have already been added, no more actions will be
        performed.

        :param emails_list: a :class:`list`/:class:`tuple`/:class:`set`
            contains the the subscribers' emails
        """

        if not hasattr(emails_list, "__iter__"):
            error_msg = "Input parameter 'emails_list' is not iterable"
            self.log.error(error_msg)
            raise exception.BadValue(error_msg)

        # overall flag
        existed_flags = False

        headers, raw_data = self._perform_subscribe()
        for email in emails_list:
            existed_flag, raw_data = self._add_subscriber(email, raw_data)
            existed_flags = existed_flags and existed_flag

        if existed_flags:
            return

        self._update_subscribe(headers, raw_data)
        self.log.info("Successfully add subscribers: %s for <Workitem %s>",
                      emails_list, self)

    def removeSubscriber(self, email):
        """Remove a subscriber from this workitem

        If the subscriber has not been added, no more actions will be
        performed.

        :param email: the subscriber's email
        """

        headers, raw_data = self._perform_subscribe()
        missing_flag, raw_data = self._remove_subscriber(email, raw_data)
        if missing_flag:
            return

        self._update_subscribe(headers, raw_data)
        self.log.info("Successfully remove a subscriber: %s for <Workitem %s>",
                      email, self)

    def removeSubscribers(self, emails_list):
        """Remove subscribers from this workitem

        If the subscribers have not been added, no more actions will be
        performed.

        :param emails_list: a :class:`list`/:class:`tuple`/:class:`set`
            contains the the subscribers' emails
        """

        if not hasattr(emails_list, "__iter__"):
            error_msg = "Input parameter 'emails_list' is not iterable"
            self.log.error(error_msg)
            raise exception.BadValue(error_msg)

        # overall flag
        missing_flags = True

        headers, raw_data = self._perform_subscribe()
        for email in emails_list:
            missing_flag, raw_data = self._remove_subscriber(email, raw_data)
            missing_flags = missing_flags and missing_flag

        if missing_flags:
            return

        self._update_subscribe(headers, raw_data)
        self.log.info("Successfully remove subscribers: %s for <Workitem %s>",
                      emails_list, self)

    def _update_subscribe(self, headers, raw_data):
        subscribers_url = "".join([self.url,
                                   "?oslc_cm.properties=rtc_cm:subscribers"])
        self.put(subscribers_url,
                 verify=False,
                 headers=headers,
                 data=xmltodict.unparse(raw_data))

    def _perform_subscribe(self):
        subscribers_url = "".join([self.url,
                                   "?oslc_cm.properties=rtc_cm:subscribers"])
        headers = copy.deepcopy(self.rtc_obj.headers)
        headers["Content-Type"] = self.OSLC_CR_RDF
        headers["Accept"] = self.OSLC_CR_RDF
        headers["OSLC-Core-Version"] = "2.0"
        resp = self.get(subscribers_url,
                        verify=False,
                        headers=headers)
        headers["If-Match"] = resp.headers.get("etag")
        raw_data = xmltodict.parse(resp.content)
        return headers, raw_data

    def _add_subscriber(self, email, raw_data):
        if not isinstance(email, six.string_types) or "@" not in email:
            excp_msg = "Please specify a valid email address name: %s" % email
            self.log.error(excp_msg)
            raise exception.BadValue(excp_msg)

        existed_flag = False
        new_subscriber = self.rtc_obj.getOwnedBy(email)
        new_sub = OrderedDict()
        new_sub["@rdf:resource"] = new_subscriber.url
        description = raw_data.get("rdf:RDF").get("rdf:Description")
        subs = description.get("rtc_cm:subscribers", None)
        if subs is None:
            # no subscribers
            added_url = "http://jazz.net/xmlns/prod/jazz/rtc/cm/1.0/"
            raw_data["rdf:RDF"]["@xmlns:rtc_cm"] = added_url
            description["rtc_cm:subscribers"] = new_sub
        else:
            if isinstance(subs, OrderedDict):
                # only one subscriber exist
                existed_flag = self._check_exist_subscriber(new_subscriber,
                                                            subs)
                if not existed_flag:
                    subs = [subs]
                    subs.append(new_sub)
                    description["rtc_cm:subscribers"] = subs
            else:
                # a list: several subscribers
                # check existing
                for exist_sub in subs:
                    existed_flag = self._check_exist_subscriber(new_subscriber,
                                                                exist_sub)
                    if existed_flag:
                        break
                else:
                    subs.append(new_sub)

        return existed_flag, raw_data

    def _remove_subscriber(self, email, raw_data):
        if not isinstance(email, six.string_types) or "@" not in email:
            excp_msg = "Please specify a valid email address name: %s" % email
            self.log.error(excp_msg)
            raise exception.BadValue(excp_msg)

        missing_flag = True
        del_sub = self.rtc_obj.getOwnedBy(email)
        description = raw_data.get("rdf:RDF").get("rdf:Description")
        subs = description.get("rtc_cm:subscribers", None)
        if subs is None:
            # no subscribers
            self.log.error("No subscribers for <Workitem %s>",
                           self)
        else:
            if isinstance(subs, OrderedDict):
                # only one subscriber exist
                missing_flag = self._check_missing_subscriber(del_sub,
                                                              subs)
                if not missing_flag:
                    description.pop("rtc_cm:subscribers")
                else:
                    self.log.error("The subscriber %s has not been "
                                   "added. No need to unsubscribe",
                                   del_sub.email)
            else:
                # a list: several subscribers
                # check existing
                for exist_sub in subs:
                    missing_flag = self._check_missing_subscriber(del_sub,
                                                                  exist_sub)
                    if not missing_flag:
                        subs.remove(exist_sub)

                        if len(subs) == 1:
                            # only one existing
                            description["rtc_cm:subscribers"] = subs[0]

                        break
                else:
                    self.log.error("The subscriber %s has not been "
                                   "added. No need to unsubscribe",
                                   del_sub.email)

        return missing_flag, raw_data

    def _check_exist_subscriber(self, new_subscriber, exist_sub):
        if new_subscriber.url == exist_sub["@rdf:resource"]:
            self.log.error("The subscriber %s has already been "
                           "added. No need to re-add",
                           new_subscriber.email)
            return True
        return False

    def _check_missing_subscriber(self, del_subscriber, exist_sub):
        if del_subscriber.url == exist_sub["@rdf:resource"]:
            self.log.error("The subscriber %s has not been "
                           "added. No need to unsubscribe",
                           del_subscriber.email)
            return False
        return True

    def getSubscribers(self):
        """Get subscribers of this workitem

        :return: a :class:`list` contains all the
            :class:`rtcclient.models.Member` objects
        :rtype: list
        """

        return self.rtc_obj._get_paged_resources("Subscribers",
                                                 workitem_id=self.identifier,
                                                 page_size="10")

    def getActions(self):
        """Get all :class:`rtcclient.models.Action` objects of this workitem

        :return: a :class:`list` contains all the
            :class:`rtcclient.models.Action` objects
        :rtype: list
        """

        cust_attr = (self.raw_data.get("rtc_cm:state")
                                  .get("@rdf:resource")
                                  .split("/")[-2])
        return self.rtc_obj._get_paged_resources("Action",
                                                 projectarea_id=self.contextId,
                                                 customized_attr=cust_attr,
                                                 page_size="100")

    def getAction(self, action_name):
        """Get the :class:`rtcclient.models.Action` object by its name

        :param action_name: the name/title of the action
        :return: the :class:`rtcclient.models.Action` object
        :rtype: rtcclient.models.Action
        """

        self.log.debug("Try to get <Action %s>", action_name)
        if not isinstance(action_name, six.string_types) or not action_name:
            excp_msg = "Please specify a valid action name"
            self.log.error(excp_msg)
            raise exception.BadValue(excp_msg)

        actions = self.getActions()

        if actions is not None:
            for action in actions:
                if action.title == action_name:
                    self.log.info("Find <Action %s>", action)
                    return action

        self.log.error("No Action named %s", action_name)
        raise exception.NotFound("No Action named %s" % action_name)

    def getStates(self):
        """Get all :class:`rtcclient.models.State` objects of this workitem

        :return: a :class:`list` contains all the
            :class:`rtcclient.models.State` objects
        :rtype: list
        """

        cust_attr = (self.raw_data.get("rtc_cm:state")
                         .get("@rdf:resource")
                         .split("/")[-2])
        return self.rtc_obj._get_paged_resources("State",
                                                 projectarea_id=self.contextId,
                                                 customized_attr=cust_attr,
                                                 page_size="50")
