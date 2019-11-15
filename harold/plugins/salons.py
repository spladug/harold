import collections
import pytz

from twisted.internet.defer import inlineCallbacks, returnValue

from harold.plugin import Plugin
from harold.utils import (
    fmt_time,
    parse_time,
)


_Salon = collections.namedtuple("Salon", "name conch_emoji deploy_hours_start deploy_hours_end tz allow_deploys")
_Repository = collections.namedtuple("Repository", "name salon branches_ format_ bundled_format_")


class WouldOrphanRepositoriesError(Exception):
    pass


class Salon(_Salon):
    @property
    def channel(self):
        return "#" + self.name.encode("utf-8")


class Repository(_Repository):
    @property
    def channel(self):
        return "#" + self.salon.encode("utf-8")

    @property
    def branches(self):
        if self.branches_:
            return self.branches_.split(",")
        else:
            return ["master"]


class SalonManagerPlugin(Plugin):
    def __init__(self, database):
        Plugin.__init__(self)
        self.database = database

    @inlineCallbacks
    def get_salons(self):
        rows = yield self.database.runQuery(
            "SELECT name, conch_emoji, deploy_hours_start, deploy_hours_end, tz, allow_deploys FROM salons"
        )

        salons = []
        for row in rows:
            name, conch_emoji, deploy_hours_start, deploy_hours_end, tz, allow_deploys = row
            salon = Salon(
                name,
                conch_emoji,
                parse_time(deploy_hours_start),
                parse_time(deploy_hours_end),
                pytz.timezone(tz),
                allow_deploys=allow_deploys,
            )
            salons.append(salon)
        returnValue(salons)

    @inlineCallbacks
    def create_salon(self, name, conch_emoji, deploy_hours_start, deploy_hours_end, tz):
        yield self.database.runOperation(
            "INSERT INTO salons (name, conch_emoji, deploy_hours_start, deploy_hours_end, tz, allow_deploys) VALUES (?, ?, ?, ?, ?, ?)",
            (name, conch_emoji, fmt_time(deploy_hours_start),
             fmt_time(deploy_hours_end), str(tz), True),
        )
        salon = Salon(
            name,
            conch_emoji,
            deploy_hours_start,
            deploy_hours_end,
            tz,
            allow_deploys=True,
        )
        returnValue(salon)

    @inlineCallbacks
    def delete_salon(self, name):
        # in case of lack of foreign keys :/
        repos = yield self.get_salon_repositories(name)
        if repos:
            raise WouldOrphanRepositoriesError

        try:
            yield self.database.runOperation(
                "DELETE FROM salons WHERE name = ?",
                (name,),
            )
        except self.database.module.IntegrityError:
            raise WouldOrphanRepositoriesError

    @inlineCallbacks
    def add_repository(self, salon_name, repository_name):
        try:
            yield self.database.runOperation(
                "INSERT INTO repositories (name, salon) VALUES (?, ?)",
                (repository_name, salon_name),
            )
        except self.database.module.IntegrityError:
            yield self.database.runOperation(
                "UPDATE repositories SET salon = ? WHERE lower(name) = lower(?)",
                (salon_name, repository_name),
            )

    @inlineCallbacks
    def remove_repository(self, salon_name, repository_name):
        yield self.database.runOperation(
            "DELETE FROM repositories WHERE lower(name) = lower(?) AND salon = ?",
            (repository_name, salon_name),
        )

    @inlineCallbacks
    def get_repository(self, repository_name):
        rows = yield self.database.runQuery(
            "SELECT name, salon, branches, format, bundled_format FROM repositories WHERE lower(name) = lower(?)",
            (repository_name,),
        )

        if rows:
            repo = Repository(*rows[0])
            returnValue(repo)
        else:
            returnValue(None)

    @inlineCallbacks
    def get_salon_repositories(self, salon_name):
        rows = yield self.database.runQuery(
            "SELECT name, salon, branches, format, bundled_format FROM repositories WHERE salon = ?",
            (salon_name,),
        )

        repos = []
        for row in rows:
            repos.append(Repository(*row))
        returnValue(repos)

    @inlineCallbacks
    def get_nick_for_user(self, github_username):
        rows = yield self.database.runQuery(
            "SELECT irc_nick FROM users WHERE github_username = ?",
            (github_username.lower(),),
        )

        if not rows:
            returnValue("@" + github_username)
        returnValue("@" + rows[0][0])

    @inlineCallbacks
    def set_nick_for_user(self, irc_nick, github_username):
        assert irc_nick

        if github_username:
            try:
                yield self.database.runOperation(
                    "INSERT INTO users (irc_nick, github_username) VALUES (?, ?)",
                    (irc_nick.lower(), github_username.lower()),
                )
            except self.database.module.IntegrityError:
                yield self.database.runOperation(
                    "UPDATE users SET github_username = ? WHERE irc_nick = ?",
                    (github_username.lower(), irc_nick.lower()),
                )
        else:
            yield self.database.runOperation(
                "DELETE FROM users WHERE irc_nick = ?",
                (irc_nick.lower(),),
            )

    @inlineCallbacks
    def set_deploy_hours(self, name, start, end, tz):
        yield self.database.runOperation(
            "UPDATE salons SET deploy_hours_start = ?, deploy_hours_end = ?, tz = ? WHERE lower(name) = ?",
            (fmt_time(start), fmt_time(end), str(tz), name),
        )

def make_plugin(database):
    return SalonManagerPlugin(database)
