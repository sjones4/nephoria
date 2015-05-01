__author__ = 'clarkmatthew'

import os
import re
import sys
# Force ansi escape sequences (markup) in output.
# This can also be set as an env var
_EUTESTER_FORCE_ANSI_ESCAPE = False
# Allow ansi color codes outside the standard range. For example some systems support
# a high intensity color range from 90-109.
# This can also be set as an env var
_EUTESTER_NON_STANDARD_ANSI_SUPPORT = False

class TEXT_STYLE():
    BOLD = 1
    FAINT = 2
    ITALIC = 3
    UNDERLINE = 4
    BLINK = 5
    BLINK_FAST = 6
    INVERSE = 7
    CONCEAL = 8
    STRIKED = 9
    html_tag_map = {
        BOLD: 'b',
        FAINT: None,
        ITALIC: 'i',
        UNDERLINE: 'u',
        BLINK: 'blink',
        BLINK_FAST: 'blink',
        INVERSE: None,
        CONCEAL: None,
        STRIKED: 'del',
    }

class FOREGROUND_COLOR():
    BLACK = 30
    RED = 31
    GREEN = 32
    YELLOW = 33
    BLUE = 34
    MAGENTA = 35
    CYAN = 36
    WHITE  = 37

class BACKGROUND_COLOR():
    BG_BLACK = 40
    BG_RED = 41
    BG_GREEN = 42
    BG_YELLOW = 43
    BG_BLUE = 44
    BG_MAGENTA = 45
    BG_CYAN = 46
    BG_WHITE  = 47


def markup(text, markups=[1], resetvalue="\033[0m", force=None, allow_nonstandard=None,
           do_html=False, html_open="<", html_close=">"):
    """
    Convenience method for using ansi markup. Attempts to check if terminal supports
    ansi escape sequences for text markups. If so will return a marked up version of the
    text supplied using the markups provided.
    Some example markeups: 1 = bold, 4 = underline, 94 = blue or markups=[1, 4, 94]
    :param text: string/buffer to be marked up
    :param markups: a value or list of values representing ansi codes.
    :param resetvalue: string used to reset the terminal, default: "\33[0m"
    :param force: boolean, if set will add escape sequences regardless of tty. Defaults to the
                  class attr '_EUTESTER_FORCE_ANSI_ESCAPE' or the env variable:
                  'EUTESTER_FORCE_ANSI_ESCAPE' if it is set.
    :param allow_nonstandard: boolean, if True all markup values will be used. If false
                              the method will attempt to remap the markup value to a
                              standard ansi value to support tools such as Jenkins, etc.
                              Defaults to the class attr '._EUTESTER_NON_STANDARD_ANSI_SUPPORT'
                              or the environment variable 'EUTESTER_NON_STANDARD_ANSI_SUPPORT'
                              if set.
    :param do_html: boolean, if True will attempt to convert the ascii escape sequences into
                    similar html tags/output
    returns a string with the provided 'text' formatted within ansi escape sequences
    """
    text = str(text)
    if not markups:
        return text
    if not isinstance(markups, list):
        markups = [markups]
    if do_html:
        startmarkup, endmarkup = _ascii_markups_to_html_tags(markups, open_bracket=html_open,
                                                             close_bracket=html_close)
    else:
        if force is None:
            force = os.environ.get('EUTESTER_FORCE_ANSI_ESCAPE', _EUTESTER_FORCE_ANSI_ESCAPE)
            if str(force).upper() == 'TRUE':
                force = True
            else:
                force = False
        if allow_nonstandard is None:
            allow_nonstandard = os.environ.get('EUTESTER_NON_STANDARD_ANSI_SUPPORT',
                                               _EUTESTER_NON_STANDARD_ANSI_SUPPORT)
            if str(allow_nonstandard).upper() == 'TRUE':
                allow_nonstandard = True
            else:
                allow_nonstandard = False
        if not force:
            if not (hasattr(sys.stdout, 'isatty') and sys.stdout.isatty()):
                return text
        if not allow_nonstandard:
           markups = _standardize_markups(markups)

        markupvalues=";".join(str(x) for x in markups)
        startmarkup = '\033[{0}m'.format(markupvalues)
        endmarkup = '\033[0m'
    lines = []
    for line in text.splitlines():
        lines.append("{0}{1}{2}".format(startmarkup, line, endmarkup))
    buf = "\n".join(lines)
    if text.endswith('\n') and not buf.endswith('\n'):
        buf += '\n'
    return buf

def _standardize_markups(markups):
    newmarkups = []
    if markups:
        if not isinstance(markups, list):
            markups = []
        for markup in markups:
            if markup > 90:
                newmarkups.append(markup-60)
            else:
                newmarkups.append(markup)
    return newmarkups

def _ascii_markups_to_html_tags(markups, open_bracket="<", close_bracket=">"):
    # '<font color="red">This is some text!</font>'
    color = None
    style_tags = []
    start_tag = ""
    end_tag = ""
    markups = _standardize_markups(markups)
    for value in markups:
        if not color:
            for fg_color in dir(FOREGROUND_COLOR):
                if getattr(FOREGROUND_COLOR, fg_color) == value:
                    color = fg_color
            if value in TEXT_STYLE.html_tag_map and TEXT_STYLE.html_tag_map[value]:
                style_tags.append(TEXT_STYLE.html_tag_map[value])
    for tag in style_tags:
        start_tag = "{0}{1}{2}{3}".format(start_tag, open_bracket, tag, close_bracket)
        end_tag = "{0}/{1}{2}{3}".format(open_bracket, tag, close_bracket, end_tag)
    if color:
        start_tag = "{0}{1}".format('{0}font color="{1}"{2}'
                                    .format(open_bracket, color, close_bracket), start_tag)
        end_tag = "{0}{1}".format(end_tag, "{0}/font{1}".format(open_bracket, close_bracket))
    return (start_tag, end_tag)










