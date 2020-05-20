#!/usr/bin/env python3
'''
Takes html generated by Doxygen and massages into "better" html.
Doxygen has partial customization (Doxyfile, header/footer/layout, css)
but it stops short of what is desired, thus here we are.
Surgically rearrange using python and BeautifulSoup, applying
many unseemly hacks.

'''

import argparse
from collections import namedtuple
import fnmatch
import os
import re
import shutil
import sys
from bs4 import BeautifulSoup, NavigableString, Tag


def Trace(msg):
    if Trace.verbose:
        sys.stderr.write((("[%s] " % Trace.current) if Trace.current else "") + str(msg) + '\n')
Trace.verbose = False
Trace.current = None

def on_blacklist(name):
    ignore = [
        'bc_s.png',
        'bdwn.png',
        'class_*-members.html',
        'classes.html',
        'closed.png',
        'dir_*.html',
        'doc.png',
    #    'doxygen.css',
        'doxygen.png',
        'dynsections.js',
        'folder*.png',
        'functions_*.html',
        'functions_func*.html',
        'globals_*.html',
        'globals_func*.html',
        'jquery.js',
        'menudata.js',
        'namespace*.html',
        'nav_*.png',
        'open.png',
        'splitbar.png',
        'sync_*.png',
        'tabs.css',
        'tab_*.png',
    ]
    for p in ignore:
        if fnmatch.fnmatch(name, p): return True
    return False

def permalink_id(link):
    """extract the Doxygen hash ref id from anchor tag"""
    target = link["href"]
    return target[target.rfind("#")+1:]

def make_usage(method_name, args):
    return "%s(%s)" % (method_name, ", ".join(args))

def parse_detail(soup, pid):
    """Doxygen hash ref id, find the target and retrieve parameter names"""
    Method = namedtuple('Method', 'name sample usage bigoh')
    permalink = soup.select_one('span.permalink a[href="#%s"]' % pid)
    if not permalink:
        permalink = soup.select_one('span.permalink a[href="#file_%s"]' % pid)
        if permalink: Trace("*** Ok, found it, but under file_id? " + pid)
    if not permalink:
        # raise Exception("No anchor for id '%s'" % pid)
        return Method("hosedown", None, "inherited", None)
    title = permalink.parent.next_sibling
    if not title: raise Exception("Could not find title for " + pid)
    name = title.string
    name = name.replace("()", "").strip()

    desc_div = permalink.find_next("div",{"class":"memitem"})
    if not desc_div: raise Exception("No memitem for id " + pid)
    param_em = desc_div.select("td.paramname em")
    param_names = [p.string for p in param_em]
    bigoh_dd = desc_div.select_one("dl.bigoh dd")
    if bigoh_dd:
        bigoh = bigoh_dd.__copy__()
    else:
        bigoh = None
    sample_dd = desc_div.select_one("dl.sample dd")
    if sample_dd:
        sample_documented = sample_dd.__copy__()
    else:
        sample_documented = None
    usage = make_usage(name, param_names)
    m = Method(name, sample_documented, usage, bigoh)
    #Trace(m)
    return m

def fix_table_headings(soup):
    '''Fixes the doxygen table headings. This includes:
        - Using bare <h2> title row instead of row embedded in <tr><td> in table
        - Putting the "name" attribute into the "id" attribute of the <tr> tag.
        - Splitting up tables into multiple separate tables if a table
            heading appears in the middle of a table.
    For example, this html:
     <table>
        <tr><td colspan="2"><h2><a name="pub-attribs"></a>
        Data Fields List</h2></td></tr>
        ...
     </table>
    would be converted to this:
     <h2>Data Fields List</h2>
     <table>
        ...
     </table>
    '''
    table_headers = []
    for tag in soup.findAll('tr'):
        if tag.td and tag.td.h2 and tag.td.h2.a and tag.td.h2.a['name']:
            tag.string = tag.td.h2.a.next
            tag.name = 'h2'
            table_headers.append(tag)
    # reverse the list so that earlier tags don't delete later tags
    table_headers.reverse()
    # Split up tables that have multiple table header (th) rows
    for tag in table_headers:
        #Trace("Header tag: %s is %s" % (tag.name, tag.string.strip()))
        # Is this a heading in the middle of a table?
        if tag.findPreviousSibling('tr') and tag.parent.name == 'table':
            Trace("Splitting Table named %s" % tag.string.strip())
            table = tag.parent
            table_parent = table.parent
            table_index = table_parent.contents.index(table)
            new_table = Tag(soup, name='table', attrs=table.attrs)
            table_parent.insert(table_index + 1, new_table)
            tag_index = table.contents.index(tag)
            for index, row in enumerate(table.contents[tag_index:]):
                new_table.insert(index, row)
        # Now move the <h2> tag to be in front of the <table> tag
        assert tag.parent.name == 'table'
        table = tag.parent
        table_parent = table.parent
        table_index = table_parent.contents.index(table)
        table_parent.insert(table_index, tag)

def tweak_member_list(soup):
    # clean up the summary list (one-line-per-member)
    for table in soup.select("table.memberdecls"):
        # set id so we can find it later
        table["id"] = "jzlist"
        # replace parameter list with just names (no types)
        # use permalink to get info from detail
        for row in table.select("tr[class^=memitem]"):
            m = None
            if row.select_one("td.memTemplParams"): continue
            name_cell = row.select_one("td.memItemRight, td.memTemplItemRight")
            if not name_cell: Trace("NO DOCUMENTATION: " + str(row))
            a = name_cell.select_one("a")
            if not a:
                #Trace("no anchor? " + str(name_cell))
                pass
            else:
                pid = permalink_id(a)
                m = parse_detail(soup, pid)
                method_name = a.string
                orig_arguments = a.next_sibling
                if orig_arguments and not isinstance(orig_arguments, NavigableString):
                    Trace("Anchor is not followed by navigable string: " + str(a) + method_name)
                    Trace(str(orig_arguments))
                    a.string.replace_with("")
                else:
                    if orig_arguments: orig_arguments.replace_with("")
                    if m.sample:
                        a.string.replace_with("")
                        a.append(m.sample)
                        m.sample.unwrap()
                    else:
                        a.string.replace_with(m.usage)
            next_row = row.find_next("tr")
            cell = next_row.select_one("td.mdescLeft")
            if cell:
                cell["class"] = "bigo"
                if m and m.bigoh:
                    cell.append(m.bigoh)
                    m.bigoh.unwrap()
                cell2 = next_row.select_one("td.mdescRight")
                cell2["class"] = "brief"
                # move two cells from second row into first
                row.append(cell)
                row.append(cell2)
            else:
                #Trace("no such cell " + str(next_row))
                cell = soup.new_tag("td", **{'class':'bigo'})
                cell2 = soup.new_tag("td", **{'class':'brief'})
                row.append(cell)
                row.append(cell2)

        # remove valign property from all table cells
        for t in table.select("td[valign]"): del t["valign"]
        # change width of all separators to full table
        for t in table.select("td[colspan]"): t["colspan"] = "3"

        # remove now-empty second rwo
        [t.decompose() for t in table.select("tr[class^=memdesc]")]

def merge_overloads(list):
    first = None
    for memitem in list:
        if not first:
            first = memitem
            continue
        proto = memitem.select_one("div.memproto")
        proto.unwrap()
        doc = memitem.select_one("div.memdoc")
        doc.unwrap()
        first.select_one("div.memproto").append(proto)
        first.select_one("div.memdoc").append(doc)

def tweak_member_detail(soup):

    for table in soup.select("table.mlabels"):
        inner = table.select_one("table.memname")
        if inner:
            table.replace_with(inner)
        else:
            Trace("did not find inner" + str(table))

    # for each member detail (long form)
    for table in soup.select("table.memname"):  # access one function
        # unwrap the (unnamed) tr that forced each param on own row
        [t.unwrap() for t in table.select("tr")]
        [t.unwrap() for t in table.select("td")]
        table.unwrap()

    for proto in soup.select("div.memproto"):  # access one function
        proto.smooth()
        # a horrid version of strip/trim
        for orig in list(proto.strings):
            cleaned = str(orig)
            cleaned = re.sub(r'\s\s+', ' ', cleaned)
            cleaned = re.sub(r'\s+\(\s+', '(', cleaned)
            cleaned = re.sub(r'\s+\)', ')', cleaned)
            cleaned = re.sub(r'<\s+(\w+)\s+>', r'<\1>', cleaned)
            cleaned = re.sub(r'\s+&', '&', cleaned)
            orig.replace_with(cleaned)

    for matches in soup.select("h2.memtitle span.overload"):
        merge_overloads(matches)





def remove_links_in_prototypes(soup):
    # find links in prototypes (e.g. parameter type, return type)
    # these are distracting, just get rid of them, unwrap to text only
    all = soup.select("td.paramtype, td.memname, td.memItemRight, td.memTemplItemRight")
    for p in (all):
        # JDZ: may need to refine this
        # match to top-level class link (not anchor)
        links = p.find_all("a", {'class':'el', 'href':re.compile('^class_\w+\.html$')})
        for l in links:
            l.unwrap()
        p.smooth()

def remove_stuff(soup):
    [t.decompose() for t in soup.select("div.navpath")]  # directory hierarchy for file pages
    [t.decompose() for t in soup.select("div.header div.summary")]  # intrapage links in header

    # summary list
    [t.decompose() for t in soup.select("td.memTemplParams")]  # template header
    [t.decompose() for t in soup.select("td.memItemLeft, td.memTemplItemLeft")]  # return type
    [t.decompose() for t in soup.select("tr[class^=separator]")]  # separator

    # detail
    [t.decompose() for t in soup.select(".mlabels-right")] # boxes for virtual/explicit/etc
    [t.decompose() for t in soup.select(".memtemplate")] # template header in detail secdtion
    [t.decompose() for t in soup.select(".memtitle")] # top tab that repeats name in detail section
    [t.decompose() for t in soup.select("dl.sample, dl.bighoh")]


def clean_doxygen(html_in):
    # first massage html, simplifies things later
    preproccesed = html_in
    # strip out any std::
    preproccesed = re.sub(r'std::', '', preproccesed)
    # remove virtual (JDZ: not sure about this)
    preproccesed = re.sub(r'virtual', '', preproccesed)

    soup = BeautifulSoup(preproccesed, features="lxml")  # now parse

    #  discard all More... links (abbreviated brief)
    [t.decompose() for t in soup.find_all("a", text="More...")]

    remove_links_in_prototypes(soup)
    tweak_member_list(soup)
    tweak_member_detail(soup)
    fix_table_headings(soup)
    remove_stuff(soup)

    cleaned = str(soup)
    return cleaned



if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('-v', '--verbose', help='verbose output',action='store_true')
    parser.add_argument('indir', help='source directory of Doxygen-generated HTML files', nargs='?', default='.')
    parser.add_argument('outdir', help='dest directory of cleaned HTML files', nargs='?', default='.')
    options = parser.parse_args(sys.argv[1:])
    Trace.verbose = True
    if options.verbose:
        Trace.verbose = True
    in_dir = options.indir
    out_dir = options.outdir
    if os.path.exists(out_dir): shutil.rmtree(out_dir)
    os.mkdir(out_dir)
    Trace( sys.argv[0] + " processing files from %s, output to %s" % (in_dir, out_dir))
    count = 0
    for root, _, files in os.walk(in_dir):
        for filename in files:
            if on_blacklist(filename):
                continue
            count += 1
            try:
                srcfile = os.path.join(in_dir, filename)
                dstfile = os.path.join(out_dir, filename)
                if os.path.splitext(filename)[1] == '.html':
                    with open(srcfile) as f:
                        contents = f.read()
                    #Trace("Cleaning " + filename)
                    Trace.current = filename
                    contents = clean_doxygen(contents)
                    with open(dstfile, 'w') as f:
                        f.write(contents)
                else:
                    shutil.copyfile(srcfile, dstfile)
            except:
                sys.stderr.write("Error while processing %s\n" % filename)
                raise

    Trace("Done. %d files in %s" % (count, out_dir))

