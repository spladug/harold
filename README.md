# Overview

Harold is a daemon whose original purpose was to inform the world via
IRC of pushes to reddit's GitHub repositories. He turned out to be
rather ambitious, though, and so he's taken on a smörgåsbord of other
responsibilities.

Harold depends on [Twisted](http://twistedmatrix.com/trac/) and is run
with `twistd`, using the `harold.tac` file. He looks for configuration
in the current directory in `harold.ini`.

# Configuring Harold

Harold is split up into distinct plugins. By default, no plugins will be
loaded or run. Plugin selection and configuration is managed via an INI
file called `harold.ini`. Each plugin has its own section, the name of
which starts with `harold:plugin:` (so the `http` plugin would appear as
`[harold:plugin:http]`). Documentation of available plugins and their
options follows.

# Plugins

## http

The HTTP plugin provides a general-purpose service that other plugins can
use to receive notifications. It doesn't do anything in itself.

### port

The port to accept HTTP requests on.

### secret

A URL-safe string that is known only by Harold and external services. Serves as
authentication that notifications are from the intended source.

## irc

A plugin which implements an IRC bot. Other plugins can use its APIs to
provide higher level features. It also provides a simple HTTP interface for
rudimentary external tools to use.

### nick

The nickname to use on IRC. Harold has no contingency code written for
a nick collision, so ensure that it will be unique.

### host

Hostname of the IRC server to connect to.

### port

Port to connect to the IRC server on.

### use\_ssl

Set to true to use an SSL connection when connecting to the IRC host.

### password

Server password to use when connecting to IRC.

### channels

A comma-delimited list of channels to join automatically. Additional channels
may be added by other plugins.

## postreceive

The postreceive plugin implements an endpoint for GitHub-style post-receive
notifications. It depends on the IRC plugin and will notify users via IRC
when code is pushed to repositories under its purview. The plugin itself does
not have any configuration (though the section header must exist in the config
file for it to be activated.) Instead, each repository that will send
notifications should have its own section of the format
`[harold:repository:owner/repository]`.

## postreceive repository configuration

### channel

IRC channel to send commit notifications to.

### branches

Comma-delimited list of branches. Only commits from
these branches will be announced. Defaults to showing commits from all branches.

### format

A python format string used to render the commit notification messages
for this repository.

Available format fields are:

* `repository` - The name of the repository on github, including owner.
* `branch` - Which branch the commit was made on.
* `url` - Link to the commit, shortened by `is.gd`.
* `commit_id` - First 7 characters of the commit SHA.
* `author` - The GitHub username, or if not present, real name of the author.
* `summary` - The first line of the commit message.

Defaults to

    %(author)s committed %(commit_id)s (%(url)s) to %(repository)s: %(summary)s

### max\_commit\_count

If a push has more than this number of commits, one bundled notification
will be sent with the format described in `bundle\_format` rather than sending
a notification for each commit.

### bundle\_format

A python format string used to render the bundled commit notification messages
for this repository.

Available format fields are:

* `repository` - The name of the repository on github, including owner.
* `branch` - Which branch the commit was made on.
* `authors` - A comma delimited list of distinct authors of commits in the set.
* `commit_count` - The number of commits in the bundle.
* `commit_range` - A git refspec showing the IDs before and after the push.
* `url` - A link to the range of commits on github. Shortened with `is.gd`.

Defaults to

    %(authors)s made %(commit_count)d commits (%(commit_range)s - %(url)s) to %(repository)s

### Configuring GitHub for postreceive

Follow the [GitHub post-receive hooks
instructions](http://help.github.com/post-receive-hooks/) and set the
post-receive URL to the following:

    http://HOST/harold/post-receive/SECRET

## ident

The ident plugin provides a simple ident server that answers all queries
with the same response. Its primary purpose is to get rid of that damned
~ on the username in IRC :)

### user

The name of the user harold will respond to all ident queries with. Defaults to "harold".

### port

The port to listen on. Defaults to the standard ident port of 113.

## jabber

The jabber plugin provides a basis for other plugins. It will maintain a connection to
jabber and has an extensible command system. To see a list of available commands when
talking to Harold via jabber, say "help".

### host

The jabber host to connect to.

### port

The port to connect to the jabber server on.

### id

The jabber ID to connect as. Should look like an email address.

### password

Password for the jabber account.

## smtp

The SMTP plugin provides an interface for other plugins to send emails.

### host

The host to relay messages through.

### port

The port to connect to the SMTP server on.

### use\_ssl

Whether or not to use SSL in the initial connection to the SMTP server.

### username / password

Credentials to authenticate with.

## alerts

This plugin provides a Jabber-based alerting system. Monitoring scripts can ping harold
via HTTP when an exceptional event occurs and harold will manage notifying the designated
recipients. Harold also provides an interface via jabber to acknowledge alerts, check their
status, and communicate among other alert recipients.

### recipients

A comma-delimited list of recipients for alert-related broadcasts. Each recipient should be
prefixed with the protocol on which to send the alert. This can be either `jabber` or `smtp`,
followed by a `:` followed by the recipient's jabber ID or email address.

### refractory\_period

The number of seconds an alert must be silent for before it is no longer considered alive.
Acknowledgements expire as soon as an alert dies.

### max\_mute\_duration

The maximum number of seconds an alert can be silenced by acknowledging it. If an alert
remains live (see `refractory\_period`) for this amount of time, further instances will
be broadcasted again. This prevents forgetting about an alert.

## alarms

The alarms plugin provides a way to send messages via IRC according to a specified schedule.
Like the `postreceive` plugin, its header must be present but actual configuration takes place
in alarm-specific sections with the prefix `harold:alarm:`.

### channel

IRC channel to send the message to.

### message

Message to send when alarm fires.

### cronspec

A cron-schedule of when the event fires.

## Example configuration file

    [harold:plugin:ident]
    port = 1113 # needs to be >1024 to not run as root. use iptables to redirect.
    user = harold

    [harold:plugin:irc]
    nick = harold_of_reddit
    host = chat.freenode.net
    port = 7000
    use_ssl = true
    password = supersecret1

    [harold:plugin:http]
    port = 8888
    secret = supersecret2

    [harold:plugin:jabber]
    host = talk.google.com
    port = 5222
    id = alertbot@reddit.com
    password = supersecret3

    [harold:plugin:smtp]
    host = smtp.gmail.com
    use_ssl = true
    port = 465
    username = redditalertbot@gmail.com
    password = whatever

    [harold:plugin:alerts]
    recipients = jabber:a@reddit.com, smtp:b@reddit.com

    [harold:plugin:postreceive]
    [harold:repository:reddit/reddit]
    channel = #reddit-dev
    format = %(author)s committed %(commit_id)s (%(url)s) to %(repository)s: %(summary)s
    [harold:repository:reddit/reddit.tv]
    channel = #reddit-dev
    format = %(author)s committed %(commit_id)s (%(url)s) to %(repository)s: %(summary)s

    [harold:plugin:alarms]
    [harold:alarm:wine]
    channel = ##reddit-office
    message = kemitche: It is now wine o'clock!
    cronspec = 48 16 * * mon-fri
    [harold:alarm:train]
    channel = ##reddit-office
    message = spladug, chromakode: It is now train o'clock!
    cronspec = 58 16 * * mon-fri

