/**
 * jspsych plugin for categorization trials with feedback
 * Josh de Leeuw
 *
 * documentation: docs.jspsych.org
 **/


jsPsych.plugins["phase1"] = (function() {

  var plugin = {};

  jsPsych.pluginAPI.registerPreload('animation', 'stimulus', 'image');

  plugin.trial = function(display_element, trial) {

    // default parameters
    trial.show_stim_with_feedback = (typeof trial.show_stim_with_feedback === 'undefined') ? true : trial.show_stim_with_feedback;
    trial.show_feedback_on_timeout = (typeof trial.show_feedback_on_timeout === 'undefined') ? false : trial.show_feedback_on_timeout;
    trial.timeout_message = trial.timeout_message || "<p>Please respond faster.</p>";
    // timing params
    trial.timing_stim = trial.timing_stim || -1; // default is to show image until response
    trial.timing_response = trial.timing_response || -1; // default is no max response time
    trial.timing_feedback_duration = trial.timing_feedback_duration || 2000;

    // if any trial variables are functions
    // this evaluates the function and replaces
    // it with the output of the function
    trial = jsPsych.pluginAPI.evaluateFunctionParameters(trial);

    // this array holds handlers from setTimeout calls
    // that need to be cleared if the trial ends early
    var setTimeoutHandlers = [];

    if (trial.season == "hot") {
      trial.background = "img/hot.png"
    } else if (trial.season == "rainy") {
      trial.background = "img/rainy.png"
    } else if (trial.season == "cold") {
      trial.background = "img/cold.png"
    } else if (trial.season == "rainbow") {
      trial.background = "img/rainbow.png"
    } else {
      trial.background = "img/blank.png"
    }

    // create Aliens, sadness, and response buttons
    var background =
      "<img src=" + trial.background + " style='position:fixed; top:0px; left:0px; bottom:0px; right: 0px' height='100%' width='100%'>"

    var c_alien_tops = [20, 80, 140, 200, 260]
    var point_tops = [0, 60, 120, 180, 240]
    alien_counters = []
    for (i = 0; i < 3; i ++) {
      alien_counter =
        trial.aliens[i] + " style='position:absolute; right:100px; top:" + c_alien_tops[i] + "px;' height=" + alien_height_point_counter + ">" +
        "<p style='position:absolute; right:0px; top:" + point_tops[i] + "px; font-size:46px;'>" + points[i] + "</p>"
      alien_counters.push(alien_counter)
    }

    point_counters =
      "<div>" +
        alien_counters[0] +
        alien_counters[1] +
        alien_counters[2] +
      "</div>"

    if (!trial.show_stim_with_feedback) {
      point_counters = " ";
    }

    sad_alien =
      "<center><div style='position:relative;'>" +
        point_counters +
        trial.aliens[trial.sad_alien] + " height=" + alien_height + ">"
        speech + exclamation_points +
      "</div></center>"

    shuffled_buttons = item_buttons  // don't shuffle buttons
    response_buttons =
      "<center><div class='response_buttons'>" +
        shuffled_buttons[0] +
        shuffled_buttons[1] +
        shuffled_buttons[2] +
      "</div></center>"

    // add Aliens, sadness, and response buttons to display
    display_element.append(background, sad_alien, response_buttons);
    trial.start_time = (new Date()).getTime();

    var trial_data = {};

    // create response function
    var after_response = function(info) {

      // kill any remaining setTimeout handlers
      for (var i = 0; i < setTimeoutHandlers.length; i++) {
        clearTimeout(setTimeoutHandlers[i]);
      }

      // clear keyboard listener
      jsPsych.pluginAPI.cancelAllKeyboardResponses();

      var correct = false;
      if (trial.key_answer == info.key) {
        correct = true;
      }
      console.log(info.key, trial.key_answer, trial.key_answer == info.key, correct)

      // get feedback amount
      feedback_amount = 0  // incorrect response or no answer
      if (correct) {  // correct response
        for (i = 0; i < key_answers.length; i++) {
          if (info.key == key_answers[i]) {
            noised_amount = trial.feedback_amounts[i] + 0.3 * randn_bm()
            rounded_amount = Math.round(noised_amount * 10) / 10  // round doesn't round with decimals
            feedback_amount = Math.max(0, rounded_amount)
          }
        }
      }

      // update point counter
      points[trial.sad_alien] += feedback_amount
      for (i = 0; i < points.length; i++) {
          points[i] = Math.round(10 * points[i]) / 10
      }

      // save data
      trial_data = {
        "rt": info.rt,
        "correct": correct,
        "reward": feedback_amount,
        "stimulus": trial.stimulus,
        "sad_alien": trial.sad_alien,
        "season": trial.season,
        "key_press": info.key,
        "points1": points[0],
        "points2": points[1],
        "points3": points[2],
        "phase": trial.phase,
      };

      display_element.html(''); // not sure what it does... remove?

      var timeout = info.rt == -1;
      doFeedback(correct, timeout);
    }

    // take care of button presses: mimic key presses
    if (input_device == "mouse") {
      function clear_button_handlers() {
        for (i = 0; i < button_names.length; i ++) {
          btn = "#".concat(button_names[i], "-button")
          $(btn).off('click');
        }
      }
      for (let i = 0; i < button_names.length; i ++) {
        btn = "#".concat(button_names[i], "-button")
        $(btn).on('click', function() {
            clear_button_handlers();
            var response_time = (new Date()).getTime();
            var rt = response_time - trial.start_time;
            info = {
              key: button_names[i],
              rt: rt
            };
            after_response(info);
        });
      }

    } else if (input_device == "keyboard") {
      jsPsych.pluginAPI.getKeyboardResponse({
        callback_function: after_response,
        valid_responses: trial.choices,
        rt_method: 'date',
        persist: false,
        allow_held_key: false
      });
    }

    if (trial.timing_response > 0) {
      setTimeoutHandlers.push(setTimeout(function() {
        after_response({
          key: -1,
          rt: -1
        });
      }, trial.timing_response));
    }

    function doFeedback(correct, timeout) {

      if (timeout && !trial.show_feedback_on_timeout) {
        display_element.append(trial.timeout_message);
      } else {

      // Add happy frame and number feedback to aliens
      alien_counters = []
      for (i = 0; i < 3; i ++) {
        alien_counter =
          trial.aliens[i] + " style='position:absolute; right:100px; top:" + c_alien_tops[i] + "px;' height=" + alien_height_point_counter + ">" +
          "<p style='position:absolute; right:0px; top:" + point_tops[i] + "px; font-size:46px;'>" + points[i] + "</p>"
        alien_counters.push(alien_counter)
      }

      point_counters =
        "<div>" +
          alien_counters[0] +
          alien_counters[1] +
          alien_counters[2] +
        "</div>"

      reward_bubble = speech + "<p style='color:green; position:absolute; left:" + reward_left + "px; top:" + reward_top + "px; font-size:46px;'> +" + feedback_amount;

      if (!trial.show_stim_with_feedback) {
        point_counters = " ";
        reward_bubble = " ";
      }

      var happy_alien =
        "<center><div style='position:relative;'>" +
          point_counters +
          trial.aliens[trial.sad_alien] + " height=" + alien_height + ">" +
          reward_bubble +
        "</div></center>"

      display_element.append(background, happy_alien, response_buttons);

      }
      setTimeout(function() {
        endTrial();
      }, trial.timing_feedback_duration);
    }

    function endTrial() {
      display_element.html("");
      point_counters =
        "<center><div style='position:relative;'>" +
          point_counters +
        "</div></center>"
      display_element.append(background, point_counters);
      jsPsych.finishTrial(trial_data);
    }

  };

  return plugin;
})();