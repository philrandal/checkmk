// +------------------------------------------------------------------+
// |             ____ _               _        __  __ _  __           |
// |            / ___| |__   ___  ___| | __   |  \/  | |/ /           |
// |           | |   | '_ \ / _ \/ __| |/ /   | |\/| | ' /            |
// |           | |___| | | |  __/ (__|   <    | |  | | . \            |
// |            \____|_| |_|\___|\___|_|\_\___|_|  |_|_|\_\           |
// |                                                                  |
// | Copyright Mathias Kettner 2010             mk@mathias-kettner.de |
// +------------------------------------------------------------------+
// 
// This file is part of Check_MK.
// The official homepage is at http://mathias-kettner.de/check_mk.
// 
// check_mk is free software;  you can redistribute it and/or modify it
// under the  terms of the  GNU General Public License  as published by
// the Free Software Foundation in version 2.  check_mk is  distributed
// in the hope that it will be useful, but WITHOUT ANY WARRANTY;  with-
// out even the implied warranty of  MERCHANTABILITY  or  FITNESS FOR A
// PARTICULAR PURPOSE. See the  GNU General Public License for more de-
// ails.  You should have  received  a copy of the  GNU  General Public
// License along with GNU Make; see the file  COPYING.  If  not,  write
// to the Free Software Foundation, Inc., 51 Franklin St,  Fifth Floor,
// Boston, MA 02110-1301 USA.

// +------------------------------------------------------------------+
// | This file has been contributed and is copyrighted by:            |
// |                                                                  |
// | Lars Michelsen <lm@mathias-kettner.de>            Copyright 2010 |
// +------------------------------------------------------------------+

var aSearchResults = [];
var iCurrent = null;
var mkSearchTargetFrame = 'main';
var oldValue = "";

// Register an input field to be a search field and add eventhandlers
function mkSearchAddField(field, targetFrame) {
    var oField = document.getElementById(field);
    if(oField) {
        if(typeof targetFrame != 'undefined') {
            mkSearchTargetFrame = targetFrame;
        }

        oField.onkeydown = function(e) { if (!e) e = window.event; return mkSearchKeyDown(e, oField); }
        oField.onkeyup   = function(e) { if (!e) e = window.event; return mkSearchKeyUp(e, oField);}
        oField.onclick   = function(e) { if (!e) e = window.event; e.cancelBubble = true; e.returnValue = false; }

        // The keypress event is being ignored. Key presses are handled by onkeydown and onkeyup events
        oField.onkeypress  = function(e) { if (!e) e = window.event; if (e.keyCode == 13) return false; }

        // On doubleclick toggle the list
        oField.ondblclick  = function(e) { if (!e) e = window.event; mkSearchToggle(e, oField); }
    }
}

mkSearchAddField("mk_side_search_field", "main");

// On key release event handler
function mkSearchKeyUp(e, oField) {
    var keyCode = e.which || e.keyCode;

    switch (keyCode) {
        // 18: Return/Enter
        // 27: Escape
        case 13:
        case 27:
            mkSearchClose();
            e.returnValue = false;
            e.cancelBubble = true;
        break;
        
        // Up/Down
        case 38:
        case 40:
            return false;
        break;

        // Other keys
        default:
            if (oField.value == "") {
                e.returnValue = false;
                e.cancelBubble = true;
                mkSearchClose();
            } 
            else {
                mkSearch(e, oField);
            }
        break;
    }
}

function find_host_url(oField)
{   
    namepart = oField.value;
    // first try to find if hostpart is a complete hostname
    // found in our list and is unique (found in only one site)
    var url = null;
    var selected_host = null;
    for (var i in aSearchHosts) {
        var hostSite  = aSearchHosts[i][0];
        var hostName  = aSearchHosts[i][1];
        if (hostName.indexOf(namepart) > -1) {
            if (url != null) { // found second match -> not unique
                url = null;
                break; // abort
            }
            url = 'view.py?view_name=host&host=' + hostName + '&site=' + hostSite;
            selected_host = hostName;
        }
    }
    if (url != null) {
        oField.value = selected_host;
        return url;
    }

    // not found, not unique or only prefix -> display a view that shows more hosts
    return 'view.py?view_name=hosts&host=' + namepart;
}

// On key press down event handler
function mkSearchKeyDown(e, oField) {
    var keyCode = e.which || e.keyCode;

    switch (keyCode) {
            // Return/Enter
            case 13:
                if (iCurrent != null) {
                    mkSearchNavigate();
                    oField.value = aSearchResults[iCurrent].name;
                    mkSearchClose();
                } else {
                    // When nothing selected, navigate with the current contents of the field
                    // TODO: Here is missing site=.... But we can add a site= only, if the entered
                    // hostname is unique and in our list.
                    top.frames[mkSearchTargetFrame].location.href = find_host_url(oField);
                    mkSearchClose();
                }
                
                e.returnValue = false;
                e.cancelBubble = true;
            break;
            
            // Escape
            case 27:
                mkSearchClose();
                e.returnValue = false;
                e.cancelBubble = true;
            break;
            
            // Up arrow
            case 38:
                if(!mkSearchResultShown()) {
                    mkSearch(e, oField);
                }
                
                mkSearchMoveElement(-1);
                return false;
            break;
            
            // Tab
            case 9:
                if(mkSearchResultShown()) {
                    mkSearchClose();
                }
                return;
            break;
            
            // Down arrow
            case 40:
                if(!mkSearchResultShown()) {
                    mkSearch(e, oField);
                }
                
                mkSearchMoveElement(1);
                return false;
            break;
        }
}

// Navigate to the target of the selected event
function mkSearchNavigate() {
    top.frames[mkSearchTargetFrame].location.href = aSearchResults[iCurrent].url;
}

// Move one step of given size in the result list
function mkSearchMoveElement(step) {
    if(iCurrent == null) {
        iCurrent = -1;
    }

    iCurrent += step;

    if(iCurrent < 0)
        iCurrent = aSearchResults.length-1;
    
    if(iCurrent > aSearchResults.length-1)
        iCurrent = 0;

    var oResults = document.getElementById('mk_search_results').childNodes;
    var a = 0;
    for(var i in oResults) {
        if(oResults[i].nodeName == 'A') {
            if(a == iCurrent) {
                oResults[i].setAttribute('class', 'active');
                oResults[i].setAttribute('className', 'active');
            } else {
                oResults[i].setAttribute('class', 'inactive');
                oResults[i].setAttribute('className', 'inactive');
            }
            a++;
        }
    }
}

// Is the result list shown at the moment?
function mkSearchResultShown() {
    var oContainer = document.getElementById('mk_search_results');
    if(oContainer) {
        oContainer = null;
        return true;
    } else
        return false;
}

// Toggle the result list
function mkSearchToggle(e, oField) {
    if(mkSearchResultShown()) {
        mkSearchClose();
    } else {
        mkSearch(e, oField);
    }
}

// Close the result list
function mkSearchClose() {
  var oContainer = document.getElementById('mk_search_results');
  if(oContainer) {
    oContainer.parentNode.removeChild(oContainer);
    oContainer = null;
  }
    
    aSearchResults = [];
    iCurrent = null;
}

// Build a new result list and show it up
function mkSearch(e, oField) {
    if(oField == null) {
        alert("Field is null");
        return;
    }
    
    var val = oField.value;
    if (val == oldValue)
        return; // nothing changed. No new search neccessary
    oldValue = val;

    if (!aSearchHosts) {
        alert("No hosts to search for");
        return;
    }

    aSearchResults = [];

    // Build matching regex
    // var oMatch = new RegExp('^'+val, 'gi');
    // switch to infix search
    var oMatch = new RegExp(val, 'gi');

    var content = '';
    var hostName, hostSite;
    for(var i in aSearchHosts){
        hostSite  = aSearchHosts[i][0];
        hostName  = aSearchHosts[i][1];

        if(hostName.match(oMatch)) {
            var oResult = {
                'id': 'result_'+hostName,
                'name': hostName,
                'site': hostSite,
                'url': 'view.py?view_name=host&host='+hostName+'&site='+hostSite
            };
            
            // Add id to search result array
            aSearchResults.push(oResult);
            content += '<a id="'+oResult.id+'" href="'+oResult.url+'" onclick="mkSearchClose()" target="'+mkSearchTargetFrame+'">'+ hostName +"</a>\n";
        }
    }

    if(content != '') {
        var oContainer = document.getElementById('mk_search_results');
        if(!oContainer) {
            var oContainer = document.createElement('div');
            oContainer.setAttribute('id', 'mk_search_results');
        }

        oContainer.innerHTML = content;

        oField.parentNode.appendChild(oContainer);

        oContainer = null;
    } else {
        mkSearchClose();
    }
    
    oField = null;
}
