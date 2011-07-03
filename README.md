# Overview

Harold is a daemon that listens on HTTP for a notification of activity from GitHub's [post-receive hooks](http://help.github.com/post-receive-hooks/) and publishes commit data to an IRC channel.

Harold is run by executing `main.py`. It looks for configuration in the current directory in `harold.ini`. Harold depends on Twisted.

# Configuring Harold

Configuration is managed with an INI file. There are two global sections, `harold:http` and `harold:irc` that configure the two services respectively. Additionally, there is a section for each GitHub repository data is expected from. The section title for each repository is prefixed with `harold:repository:`. Notifications for repositories not listed in the configuration file will be silently ignored.

## HTTP Configuration

### port

The port to listen for notifications on.

### secret

A URL-safe string that is known only by Harold and GitHub. Serves as authentication that the notifications are genuine.

## IRC Configuration

### nick

The nickname to use on IRC. Harold has no contingency code written for a nick collision, so ensure that it will be unique.

### host

Hostname of the IRC server to connect to.

### port

Port to connect to the IRC server on.

### use\_ssl

Set to true to enable an SSL connection to IRC.

### password

Server password to use when connecting to IRC.

## Repository Configuration

### channel

IRC channel to send commit notifications to.

### format

A python format string used to render the commit notification messages for this repository.

Available format fields are:

* `repository` - The name of the repository on github, including owner.
* `url` - Link to the commit, shortened by `is.gd`.
* `commit_id` - First 7 characters of the commit SHA.
* `author` - The GitHub username, or if not present, real name of the author.
* `summary` - The first line of the commit message.

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

# Configuring GitHub

Follow the [GitHub post-receive hooks instructions](http://help.github.com/post-receive-hooks/) and set the post-receive URL to the following:

    http://HOST/harold/post-receive/SECRET
