# Overview

Harold is a daemon that listens on HTTP for a
notification of activity from GitHub's [post-receive
hooks](http://help.github.com/post-receive-hooks/) and publishes commit
data to an IRC channel.

Harold depends on Twisted and is run with `twistd`, using the `harold.tac`
file. It looks for configuration in the current directory in `harold.ini`.

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

Server password to use when connecting to IRC, frequently used for chanserv.

### channels

A comma-delimited list of channels to join automatically. Additional channels
may be added by other plugins (such as the postreceive plugin).

## postreceive

The postreceive plugin implements and endpoint for GitHub-style post-receive
notifications. It depends on the IRC plugin and will notify users via IRC
when code is pushed to repositories under its purvue. The plugin itself does
not have any configuration (though the section header must exist in the config
file for it to be activated.) Instead, each repository that will send
notifications should have its own section of the format
`[harold:repository:owner/repository]`.

## postreceive repository configuration

### channel

IRC channel to send commit notifications to.

### branches

Comma-delimited list of branches. Only commits from
these branches will be announced. Defaults to showing all commits.

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

## Example configuration file

    [DEFAULT]
    format = %(author)s committed %(commit_id)s (%(url)s) to %(repository)s: %(summary)s

    [harold:irc]
    nick = Harold
    host = chat.freenode.net
    port = 7000 
    use_ssl = true 
    password = supersecret

    [harold:http]
    port = 8888
    secret = abcdef

    [harold:repository:reddit/reddit]
    channel = #reddit-dev

    [harold:repository:spladug/harold]
    channel = #spladug
    format = New commit! %(commit_id)s

